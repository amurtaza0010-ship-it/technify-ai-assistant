"""
LLM client configuration for TAIA.
"""
import logging
import os
import time
from collections.abc import AsyncIterator
from typing import Sequence

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage
from langchain_openai import ChatOpenAI

from app.config import get_settings

load_dotenv()

logger = logging.getLogger("taia.llm")

LLM_CONNECTION_ERROR = (
    "I couldn't connect to the AI service. Please check the backend logs "
    "to ensure the API key is valid."
)

LLM_RATE_LIMIT_BUSY = (
    "I'm currently experiencing high traffic, please try again in a few seconds."
)

_KEY_ENV_VARS = ("GROQ_API_KEY", "LLM_API_KEY", "OPENAI_API_KEY")
_FALLBACK_MAX_TOKENS = int(os.getenv("LLM_FALLBACK_MAX_TOKENS", "800"))

_settings = get_settings()
PRIMARY_MODEL = _settings.LLM_PRIMARY_MODEL
FALLBACK_MODEL = _settings.LLM_FALLBACK_MODEL
MAIN_MODEL = PRIMARY_MODEL
CLASSIFIER_MODEL = os.getenv("LLM_CLASSIFIER_MODEL", FALLBACK_MODEL)
_api_key_checked = False
_llm_cache: dict[tuple, ChatOpenAI] = {}


def _resolve_api_key() -> str | None:
    for env_var in _KEY_ENV_VARS:
        key = os.getenv(env_var, "").strip()
        if key:
            return key
    return None


def _resolve_base_url(api_key: str) -> str:
    explicit = os.getenv("LLM_BASE_URL", "").strip()
    if explicit:
        return explicit
    if api_key.startswith("gsk_"):
        return "https://api.groq.com/openai/v1"
    return os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")


def check_llm_api_key() -> bool:
    """Log whether an LLM API key is present at runtime (once per process)."""
    groq_api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not groq_api_key:
        resolved = _resolve_api_key()
        if not resolved:
            logger.critical("GROQ_API_KEY is empty or missing from .env file")
            return False
        logger.info("LLM API key loaded via fallback env var")
        return True

    logger.info("GROQ_API_KEY loaded successfully")
    return True


def get_llm(
    model: str | None = None,
    max_tokens: int | None = None,
    streaming: bool = False,
) -> ChatOpenAI:
    """Return a configured LangChain ChatOpenAI client for the given model."""
    global _api_key_checked
    if not _api_key_checked:
        if not check_llm_api_key():
            raise ValueError("LLM API key is not configured")
        _api_key_checked = True

    api_key = _resolve_api_key()
    if not api_key:
        raise ValueError("LLM API key is not configured")

    resolved_model = model or PRIMARY_MODEL
    cache_key = (resolved_model, max_tokens, streaming)
    if cache_key in _llm_cache:
        return _llm_cache[cache_key]

    kwargs: dict = {
        "api_key": api_key,
        "base_url": _resolve_base_url(api_key),
        "model": resolved_model,
        "temperature": float(os.getenv("LLM_TEMPERATURE", "0.3")),
        "streaming": streaming,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    client = ChatOpenAI(**kwargs)
    _llm_cache[cache_key] = client
    return client


def is_llm_auth_error(error: Exception) -> bool:
    message = str(error).lower()
    return any(
        phrase in message
        for phrase in (
            "missing authentication",
            "401",
            "unauthorized",
            "invalid api key",
            "authentication error",
        )
    )


def is_rate_limit_error(error: Exception) -> bool:
    """Detect Groq/OpenAI rate limits (HTTP 429) including Groq RateLimitError."""
    if is_llm_auth_error(error):
        return False

    exc_name = type(error).__name__.lower()
    if "ratelimit" in exc_name:
        return True

    status_code = getattr(error, "status_code", None)
    if status_code == 429:
        return True

    response = getattr(error, "response", None)
    if response is not None and getattr(response, "status_code", None) == 429:
        return True

    message = str(error).lower()
    return any(
        phrase in message
        for phrase in (
            "429",
            "rate limit",
            "rate_limit",
            "ratelimiterror",
            "tokens per day",
            "tpm",
            "too many requests",
        )
    )


async def ainvoke_classifier_llm(messages: Sequence[BaseMessage]) -> BaseMessage:
    """Fast intent-router call using LLM_CLASSIFIER_MODEL (default: 8b instant)."""
    t0 = time.perf_counter()
    classifier = get_llm(model=CLASSIFIER_MODEL, max_tokens=32)
    try:
        result = await classifier.ainvoke(messages)
        logger.info(
            "LLM classifier %s → %.2fs",
            CLASSIFIER_MODEL,
            time.perf_counter() - t0,
        )
        return result
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        if is_rate_limit_error(exc):
            logger.warning(
                "Classifier rate limited (%s) after %.2fs; intent falls back to 'general'",
                CLASSIFIER_MODEL,
                elapsed,
            )
            return AIMessage(content="general")
        logger.warning(
            "Classifier %s failed after %.2fs: %s",
            CLASSIFIER_MODEL,
            elapsed,
            exc,
        )
        raise


async def ainvoke_llm_with_fallback(messages: Sequence[BaseMessage]) -> BaseMessage:
    """
    Invoke PRIMARY_MODEL; on 429, retry once with FALLBACK_MODEL.
    If both are rate-limited, return a friendly busy message (no raw 429).
    """
    temperature = float(os.getenv("LLM_TEMPERATURE", "0.3"))
    primary = get_llm(model=PRIMARY_MODEL)
    t0 = time.perf_counter()

    try:
        result = await primary.ainvoke(messages)
        logger.info(
            "LLM primary %s → %.2fs",
            PRIMARY_MODEL,
            time.perf_counter() - t0,
        )
        return result
    except Exception as primary_exc:
        elapsed = time.perf_counter() - t0
        if not is_rate_limit_error(primary_exc):
            logger.warning(
                "LLM primary %s failed (non-rate-limit) after %.2fs: %s",
                PRIMARY_MODEL,
                elapsed,
                primary_exc,
            )
            raise

        logger.warning(
            "LLM primary rate limited (%s) after %.2fs — retrying with %s (reason: HTTP 429 / rate limit)",
            PRIMARY_MODEL,
            elapsed,
            FALLBACK_MODEL,
        )

        fallback = get_llm(model=FALLBACK_MODEL, max_tokens=_FALLBACK_MAX_TOKENS)
        t1 = time.perf_counter()
        try:
            result = await fallback.ainvoke(messages)
            logger.info(
                "LLM fallback %s → %.2fs (triggered by primary rate limit)",
                FALLBACK_MODEL,
                time.perf_counter() - t1,
            )
            return result
        except Exception as fallback_exc:
            fb_elapsed = time.perf_counter() - t1
            if is_rate_limit_error(fallback_exc):
                logger.warning(
                    "Fallback LLM also rate limited (%s) after %.2fs; returning busy message",
                    FALLBACK_MODEL,
                    fb_elapsed,
                )
                return AIMessage(content=LLM_RATE_LIMIT_BUSY)
            raise


async def astream_llm_with_fallback(
    messages: Sequence[BaseMessage],
) -> AsyncIterator[str]:
    """
    Stream PRIMARY_MODEL token chunks; on 429, retry once with FALLBACK_MODEL.
    If both are rate-limited, yield the friendly busy message once.
    """
    temperature = float(os.getenv("LLM_TEMPERATURE", "0.3"))
    primary = get_llm(model=PRIMARY_MODEL, streaming=True)
    t0 = time.perf_counter()

    try:
        async for chunk in primary.astream(messages):
            if chunk.content:
                yield chunk.content
        logger.info(
            "LLM stream primary %s → %.2fs",
            PRIMARY_MODEL,
            time.perf_counter() - t0,
        )
        return
    except Exception as primary_exc:
        elapsed = time.perf_counter() - t0
        if not is_rate_limit_error(primary_exc):
            logger.warning(
                "LLM stream primary %s failed (non-rate-limit) after %.2fs: %s",
                PRIMARY_MODEL,
                elapsed,
                primary_exc,
            )
            raise

        logger.warning(
            "LLM stream primary rate limited (%s) after %.2fs — retrying with %s",
            PRIMARY_MODEL,
            elapsed,
            FALLBACK_MODEL,
        )

        fallback = get_llm(
            model=FALLBACK_MODEL,
            max_tokens=_FALLBACK_MAX_TOKENS,
            streaming=True,
        )
        t1 = time.perf_counter()
        try:
            async for chunk in fallback.astream(messages):
                if chunk.content:
                    yield chunk.content
            logger.info(
                "LLM stream fallback %s → %.2fs (triggered by primary rate limit)",
                FALLBACK_MODEL,
                time.perf_counter() - t1,
            )
        except Exception as fallback_exc:
            if is_rate_limit_error(fallback_exc):
                logger.warning(
                    "Fallback LLM stream also rate limited (%s); yielding busy message",
                    FALLBACK_MODEL,
                )
                yield LLM_RATE_LIMIT_BUSY
            else:
                raise


TAIA_IDENTITY_SYSTEM = """RESPONSE STYLE RULES (follow strictly):
- Match response length to question complexity. Simple question = 1-2 sentence answer.
- NEVER repeat your full introduction after the first message in a conversation.
- Be friendly and conversational, not robotic or overly formal.
- Small talk gets small talk back. Academic queries get detailed answers.
- Do not explain what you are or what you do unless directly asked.

You are TAIA (Technify Academic AI Assistant), an intelligent AI assistant built by Technify Software House. You are a bot, NOT the user. NEVER introduce the user's details when you are asked about yourself.

Your purpose is to help university students, faculty, and admins with ERP queries such as attendance, grades, fees, timetables, and policies.

CRITICAL IDENTITY RULES:
1. You are TAIA — the AI assistant. You are NOT the user.
2. Never confuse yourself with the logged-in user. Never say you are the user or use the user's name as your own.
3. When the user asks about YOU ("Who are you?", "Tell me about yourself", "What is your name?" meaning the bot), answer ONLY what was asked — do not volunteer a full introduction unless they explicitly request one.
4. When the user asks about THEMSELVES ("Who am I?", "What is my name?", "What is my profile?"), their session data will be provided separately in that turn only — use it then, not otherwise.
5. Be polite, professional, and accurate. Never reveal one user's data to another user.
"""
