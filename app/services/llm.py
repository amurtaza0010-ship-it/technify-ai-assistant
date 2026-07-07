"""

LLM client configuration for TAIA.

Architecture: Groq primary → OpenRouter fallback → Gemini Flash fallback (multi‑model) → static message on failure.

"""

import asyncio

import logging

import os

import re

import threading

import time

from collections import deque

from collections.abc import AsyncIterator

from datetime import date

from typing import Sequence

import google.generativeai as genai

import httpx

from dotenv import load_dotenv

from langchain_core.messages import AIMessage, BaseMessage

from langchain_openai import ChatOpenAI

from app.config import get_settings


load_dotenv()


logger = logging.getLogger("taia.llm")

logger.info("LLM Mode: Groq primary | OpenRouter fallback | Gemini Flash fallback")


GROQ_PRIMARY_MODEL = os.getenv("GROQ_PRIMARY_MODEL", "llama-3.1-8b-instant")

_GROQ_DAILY_TOKEN_BUDGET = int(os.getenv("GROQ_DAILY_TOKEN_BUDGET", "1000000"))

_GROQ_429_MAX_RETRIES = int(os.getenv("GROQ_429_MAX_RETRIES", "2"))

_GROQ_429_DEFAULT_WAIT = 5.0

_groq_tokens_used_today = 0

_groq_token_day: date | None = None


LLM_CONNECTION_ERROR = (

    "I couldn't connect to the AI service. Please check the backend logs "

    "to ensure the API key is valid."

)


LLM_RATE_LIMIT_BUSY = (

    "I'm currently experiencing high traffic, please try again in a few seconds."

)


LLM_STATIC_FALLBACK = (

    "I'm currently overloaded. Please try again in a few minutes."

)


_KEY_ENV_VARS = ("GROQ_API_KEY", "LLM_API_KEY", "OPENAI_API_KEY")


_settings = get_settings()

PRIMARY_MODEL = _settings.LLM_PRIMARY_MODEL or GROQ_PRIMARY_MODEL

MAIN_MODEL = PRIMARY_MODEL

# ── OpenRouter fallback ──
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# ── Gemini fallback: try multiple models if the first one hits its quota ──
GEMINI_FALLBACK_MODELS = [
    os.getenv("GEMINI_MODEL", "models/gemini-2.0-flash"),
    "models/gemini-2.5-flash",
]

_api_key_checked = False

_groq_cache: dict[tuple, ChatOpenAI] = {}

_openrouter_client: ChatOpenAI | None = None


def _get_openrouter_client() -> ChatOpenAI:
    """Return a ChatOpenAI client pointed at OpenRouter."""
    global _openrouter_client
    if _openrouter_client is not None:
        return _openrouter_client
    if not OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY is not configured")
    _openrouter_client = ChatOpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL,
        model=OPENROUTER_MODEL,
        temperature=float(os.getenv("LLM_TEMPERATURE", "0.3")),
        streaming=False,
        max_retries=0,
        timeout=30.0,
    )
    return _openrouter_client


def _get_openrouter_streaming_client() -> ChatOpenAI:
    """Return a streaming ChatOpenAI client pointed at OpenRouter."""
    client = ChatOpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL,
        model=OPENROUTER_MODEL,
        temperature=float(os.getenv("LLM_TEMPERATURE", "0.3")),
        streaming=True,
        max_retries=0,
        timeout=30.0,
    )
    return client


def _resolve_groq_api_key() -> str | None:

    for env_var in _KEY_ENV_VARS:

        key = os.getenv(env_var, "").strip()

        if key:

            return key

    return None


def _resolve_groq_base_url() -> str:

    explicit = os.getenv("LLM_BASE_URL", "").strip()

    if explicit:

        return explicit

    return "https://api.groq.com/openai/v1"


def check_llm_api_key() -> bool:

    """Verify Groq API key is configured for the primary provider."""

    groq_api_key = os.getenv("GROQ_API_KEY", "").strip()

    if groq_api_key:

        logger.info("GROQ_API_KEY loaded successfully")

        return True

    resolved = _resolve_groq_api_key()

    if resolved:

        logger.info("LLM API key loaded via fallback env var")

        return True

    logger.critical("GROQ_API_KEY is empty or missing from .env file")

    return False


def get_llm(

    model: str | None = None,

    max_tokens: int | None = None,

    streaming: bool = False,

) -> ChatOpenAI:

    """Return a Groq ChatOpenAI client (primary provider only)."""

    global _api_key_checked

    if not _api_key_checked:

        if not check_llm_api_key():

            raise ValueError("LLM API key is not configured")

        _api_key_checked = True

    resolved_model = model or PRIMARY_MODEL

    cache_key = (resolved_model, max_tokens, streaming)

    if cache_key in _groq_cache:

        return _groq_cache[cache_key]

    api_key = _resolve_groq_api_key()

    if not api_key:

        raise ValueError("LLM API key is not configured")

    kwargs: dict = {

        "api_key": api_key,

        "base_url": _resolve_groq_base_url(),

        "model": resolved_model,

        "temperature": float(os.getenv("LLM_TEMPERATURE", "0.3")),

        "streaming": streaming,

        "max_retries": 0,

        "timeout": 30.0,

    }

    if max_tokens is not None:

        kwargs["max_tokens"] = max_tokens

    client = ChatOpenAI(**kwargs)

    _groq_cache[cache_key] = client

    return client


def _iter_error_chain(error: BaseException):

    seen: set[int] = set()

    current: BaseException | None = error

    while current is not None and id(current) not in seen:

        seen.add(id(current))

        yield current

        current = current.__cause__ or current.__context__


def _message_indicates_rate_limit(message: str) -> bool:

    lower = message.lower()

    if re.search(r"\b429\b", lower):

        return True

    return any(

        phrase in lower

        for phrase in (

            "rate limit",

            "rate_limit",

            "rate_limit_exceeded",

            "ratelimiterror",

            "tokens per minute",

            "tokens per minute exceeded",

            "too many requests",

        )

    )


def is_rate_limit_error(error: Exception) -> bool:

    return any(_exception_indicates_rate_limit(exc) for exc in _iter_error_chain(error))


def is_direct_rate_limit_error(error: Exception) -> bool:

    return _exception_indicates_rate_limit(error)


def _exception_indicates_rate_limit(exc: BaseException) -> bool:

    exc_name = type(exc).__name__.lower()

    if "ratelimit" in exc_name:

        return True

    status_code = getattr(exc, "status_code", None)

    if status_code == 429:

        return True

    response = getattr(exc, "response", None)

    if response is not None:

        response_status = getattr(response, "status_code", None)

        if response_status == 429:

            return True

        try:

            body = response.json()

            error_code = (body.get("error") or {}).get("code", "")

            if error_code == "rate_limit_exceeded":

                return True

        except Exception:

            pass

    return _message_indicates_rate_limit(str(exc))


def is_llm_auth_error(error: Exception) -> bool:

    if is_rate_limit_error(error):

        return False

    message = str(error).lower()

    if _message_indicates_rate_limit(message):

        return False

    return any(

        phrase in message

        for phrase in (

            "missing authentication",

            "unauthorized",

            "invalid api key",

            "authentication error",

        )

    ) or bool(re.search(r"(?:error code:\s*401|\b401 unauthorized\b)", message))


def _groq_failure_allows_static_fallback(exc: Exception) -> bool:

    return not is_llm_auth_error(exc)


def _groq_error_message(exc: BaseException) -> str:

    if isinstance(exc, httpx.HTTPStatusError):

        try:

            body = exc.response.json()

            message = (body.get("error") or {}).get("message", "")

            if message:

                return str(message)

        except Exception:

            pass

    response = getattr(exc, "response", None)

    if response is not None:

        try:

            body = response.json()

            message = (body.get("error") or {}).get("message", "")

            if message:

                return str(message)

        except Exception:

            pass

    return str(exc)


def _parse_groq_retry_wait_seconds(exc: Exception) -> float:

    """Extract 'try again in Xs' from a Groq 429 error; default 5 seconds."""

    message = _groq_error_message(exc)

    match = re.search(r"try again in\s+([\d.]+)\s*s", message, re.IGNORECASE)

    if match:

        try:

            return float(match.group(1))

        except ValueError:

            pass

    return _GROQ_429_DEFAULT_WAIT


def _is_groq_429_error(exc: Exception) -> bool:

    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:

        return True

    return is_direct_rate_limit_error(exc)


def _chunk_text(content) -> str:

    if isinstance(content, str):

        return content

    if isinstance(content, list):

        parts = []

        for item in content:

            if isinstance(item, dict):

                parts.append(str(item.get("text", "")))

            elif item:

                parts.append(str(item))

        return "".join(parts)

    return str(content) if content else ""


# ── OpenRouter fallback helpers ──

async def _ainvoke_openrouter_fallback(messages: Sequence[BaseMessage]) -> AIMessage | None:
    """Invoke OpenRouter GPT-4o-mini for non-streaming."""
    if not OPENROUTER_API_KEY:
        logger.warning("OpenRouter fallback skipped: no API key")
        return None
    try:
        logger.info("Switching to OpenRouter fallback: %s", OPENROUTER_MODEL)
        client = _get_openrouter_client()
        response = await client.ainvoke(list(messages))
        return AIMessage(content=_chunk_text(response.content))
    except Exception as exc:
        logger.warning("OpenRouter fallback failed: %s", exc)
        return None


async def stream_openrouter_fallback(messages: Sequence[BaseMessage]) -> AsyncIterator[str]:
    """Stream OpenRouter GPT-4o-mini response chunks."""
    if not OPENROUTER_API_KEY:
        logger.warning("OpenRouter fallback skipped: no API key")
        return
    try:
        logger.info("Switching to OpenRouter fallback stream: %s", OPENROUTER_MODEL)
        client = _get_openrouter_streaming_client()
        async for chunk in client.astream(list(messages)):
            text = _chunk_text(chunk.content)
            if text:
                yield text
    except Exception as exc:
        logger.warning("OpenRouter stream fallback failed: %s", exc)


# ── Gemini fallback helpers ──

def _messages_to_gemini_prompt(messages: Sequence[BaseMessage]) -> str:
    parts: list[str] = []
    for msg in messages:
        cls_name = type(msg).__name__
        if cls_name == "SystemMessage":
            role = "system"
        elif cls_name == "AIMessage":
            role = "assistant"
        else:
            role = "user"
        content = _chunk_text(getattr(msg, "content", ""))
        if content:
            parts.append(f"{role.upper()}: {content}")
    return "\n\n".join(parts)


async def stream_gemini_fallback(messages: Sequence[BaseMessage]) -> AsyncIterator[str]:
    """Stream Gemini Flash response, trying multiple models on failure."""
    prompt = _messages_to_gemini_prompt(messages)
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not configured")

    for model_name in GEMINI_FALLBACK_MODELS:
        logger.info("Switching to Gemini fallback: %s", model_name)
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(model_name)

            if hasattr(model, "generate_content_async"):
                response = await model.generate_content_async(prompt, stream=True)
                async for chunk in response:
                    text = getattr(chunk, "text", None) or ""
                    if text:
                        yield text
                return
            else:
                loop = asyncio.get_running_loop()
                queue: asyncio.Queue = asyncio.Queue()
                _sentinel = object()

                def _producer() -> None:
                    try:
                        for chunk in model.generate_content(prompt, stream=True):
                            text = getattr(chunk, "text", None) or ""
                            if text:
                                loop.call_soon_threadsafe(queue.put_nowait, text)
                    except Exception as exc:
                        loop.call_soon_threadsafe(queue.put_nowait, exc)
                    finally:
                        loop.call_soon_threadsafe(queue.put_nowait, _sentinel)

                threading.Thread(target=_producer, daemon=True).start()

                while True:
                    item = await queue.get()
                    if item is _sentinel:
                        break
                    if isinstance(item, Exception):
                        raise item
                    yield item
                return
        except Exception as exc:
            logger.warning("Gemini model %s failed: %s", model_name, exc)
            continue

    logger.warning("All Gemini fallback models failed")


async def _ainvoke_gemini_fallback(messages: Sequence[BaseMessage]) -> AIMessage | None:
    try:
        parts: list[str] = []
        async for text in stream_gemini_fallback(messages):
            parts.append(text)
        content = "".join(parts)
        if content.strip():
            return AIMessage(content=content)
    except Exception as exc:
        logger.warning("Gemini fallback failed: %s", exc)
    return None


def _reset_token_counter_if_new_day() -> None:

    global _groq_tokens_used_today, _groq_token_day

    today = date.today()

    if _groq_token_day != today:

        _groq_tokens_used_today = 0

        _groq_token_day = today


def _estimate_tokens(messages):

    total_chars = sum(len(str(getattr(msg, 'content', ''))) for msg in messages)

    input_estimate = max(1, total_chars // 3)

    output_reserve = 800

    return input_estimate + output_reserve


def _get_remaining_daily_tokens() -> int:

    _reset_token_counter_if_new_day()

    return max(0, _GROQ_DAILY_TOKEN_BUDGET - _groq_tokens_used_today)


def _record_groq_token_usage(messages: Sequence[BaseMessage], response_text: str = "") -> None:

    global _groq_tokens_used_today

    _reset_token_counter_if_new_day()

    _groq_tokens_used_today += _estimate_tokens(messages) + max(1, len(response_text) // 4)


def _groq_token_budget_exceeded(messages: Sequence[BaseMessage]) -> bool:

    estimated = _estimate_tokens(messages)

    remaining = _get_remaining_daily_tokens()

    if estimated > remaining:

        logger.info(

            "Token budget exceeded (estimated=%s, remaining=%s); skipping Groq",

            estimated,

            remaining,

        )

        return True

    return False


# ---------- Per-minute rate limiter (TPM) ----------
_TPM_WINDOW = 60
_TPM_LIMIT = int(os.getenv("GROQ_TPM_LIMIT", "6000"))
_tpm_log: deque[tuple[float, int]] = deque()


def _current_tpm() -> int:
    """Sum of tokens used in the last _TPM_WINDOW seconds."""
    now = time.time()
    while _tpm_log and _tpm_log[0][0] < now - _TPM_WINDOW:
        _tpm_log.popleft()
    return sum(tokens for _, tokens in _tpm_log)


def _would_exceed_tpm(estimated_tokens: int) -> bool:
    """Return True if adding estimated_tokens would exceed the TPM limit."""
    return (_current_tpm() + estimated_tokens) > _TPM_LIMIT


def _record_tpm(tokens: int) -> None:
    """Record that tokens were just used."""
    _tpm_log.append((time.time(), tokens))


def _groq_tpm_would_be_exceeded(messages: Sequence[BaseMessage]) -> bool:
    estimated = _estimate_tokens(messages)
    if _would_exceed_tpm(estimated):
        logger.info(
            "TPM limit would be exceeded (estimated=%s, current=%s, limit=%s); "
            "pre‑emptively falling back",
            estimated,
            _current_tpm(),
            _TPM_LIMIT,
        )
        return True
    return False


def _extract_groq_token_usage(
    result: BaseMessage,
    messages: Sequence[BaseMessage],
    response_text: str = "",
) -> int:
    metadata = getattr(result, "response_metadata", None) or {}
    usage = metadata.get("token_usage") or metadata.get("usage") or {}
    if isinstance(usage, dict):
        total = usage.get("total_tokens")
        if total is not None:
            return int(total)
    return _estimate_tokens(messages) + max(1, len(response_text) // 4)


async def ainvoke_classifier_llm(messages: Sequence[BaseMessage]) -> AIMessage:

    """Intent routing is heuristic-only; never call an LLM for classification."""

    return AIMessage(content="general")


async def ainvoke_llm_with_fallback(

    messages: Sequence[BaseMessage],

) -> BaseMessage:

    """Groq primary → OpenRouter → Gemini → static message."""

    # Daily budget exceeded → skip Groq, go to OpenRouter
    if _groq_token_budget_exceeded(messages):
        or_result = await _ainvoke_openrouter_fallback(messages)
        if or_result is not None:
            return or_result
        gemini_result = await _ainvoke_gemini_fallback(messages)
        return gemini_result or AIMessage(content=LLM_STATIC_FALLBACK)

    # Pre‑emptively fall back when TPM would be exceeded
    if _groq_tpm_would_be_exceeded(messages):
        logger.info("Pre‑emptively falling back due to TPM limit")
        or_result = await _ainvoke_openrouter_fallback(messages)
        if or_result is not None:
            return or_result
        gemini_result = await _ainvoke_gemini_fallback(messages)
        return gemini_result or AIMessage(content=LLM_STATIC_FALLBACK)

    t0 = time.perf_counter()

    estimated = _estimate_tokens(messages)
    total_chars = sum(len(str(getattr(m, "content", ""))) for m in messages)
    logger.info(
        "Groq request: ~%d tokens (~%.1f KB prompt)",
        estimated,
        total_chars / 1024,
    )

    groq = get_llm(model=PRIMARY_MODEL)

    groq_exc: Exception | None = None

    for attempt in range(_GROQ_429_MAX_RETRIES + 1):

        try:

            result = await groq.ainvoke(messages)

            response_text = _chunk_text(result.content)

            _record_groq_token_usage(messages, response_text)

            _record_tpm(_extract_groq_token_usage(result, messages, response_text))

            logger.info(

                "LLM Groq primary %s → %.2fs",

                PRIMARY_MODEL,

                time.perf_counter() - t0,

            )

            return result

        except Exception as exc:

            groq_exc = exc

            if is_llm_auth_error(exc):

                logger.warning(

                    "Groq auth failed after %.2fs: %s",

                    time.perf_counter() - t0,

                    exc,

                )

                raise

            if _is_groq_429_error(exc) and attempt < _GROQ_429_MAX_RETRIES:

                wait_seconds = _parse_groq_retry_wait_seconds(exc)

                logger.warning(

                    "Groq rate limited (429); retrying in %.1fs (attempt %s/%s)",

                    wait_seconds + 1,

                    attempt + 1,

                    _GROQ_429_MAX_RETRIES,

                )

                await asyncio.sleep(wait_seconds + 1)

                continue

            if not _groq_failure_allows_static_fallback(exc):

                logger.warning(

                    "Groq failed after %.2fs: %s",

                    time.perf_counter() - t0,

                    exc,

                )

                raise

            break

    logger.warning(

        "Groq rate limited or unavailable after %.2fs (%s); trying OpenRouter fallback.",

        time.perf_counter() - t0,

        groq_exc,

    )

    or_result = await _ainvoke_openrouter_fallback(messages)
    if or_result is not None:
        return or_result

    logger.info("OpenRouter fallback failed; trying Gemini fallback.")
    gemini_result = await _ainvoke_gemini_fallback(messages)

    return gemini_result or AIMessage(content=LLM_STATIC_FALLBACK)


async def astream_llm_with_fallback(

    messages: Sequence[BaseMessage],

) -> AsyncIterator[str]:

    """Groq stream primary → OpenRouter → Gemini → static message."""

    # Daily budget exceeded → skip Groq, go to OpenRouter
    if _groq_token_budget_exceeded(messages):
        try:
            async for text in stream_openrouter_fallback(messages):
                yield text
            return
        except Exception as exc:
            logger.warning("OpenRouter stream fallback failed: %s", exc)
        try:
            async for text in stream_gemini_fallback(messages):
                yield text
            return
        except Exception as exc:
            logger.warning("Gemini stream fallback failed: %s", exc)
        yield LLM_STATIC_FALLBACK
        return

    # Pre‑emptively fall back when TPM would be exceeded
    if _groq_tpm_would_be_exceeded(messages):
        logger.info("Pre‑emptively falling back due to TPM limit")
        try:
            async for text in stream_openrouter_fallback(messages):
                yield text
            return
        except Exception as exc:
            logger.warning("OpenRouter stream fallback failed: %s", exc)
        try:
            async for text in stream_gemini_fallback(messages):
                yield text
            return
        except Exception as exc:
            logger.warning("Gemini stream fallback failed: %s", exc)
        yield LLM_STATIC_FALLBACK
        return

    t0 = time.perf_counter()

    estimated = _estimate_tokens(messages)
    total_chars = sum(len(str(getattr(m, "content", ""))) for m in messages)
    logger.info(
        "Groq stream request: ~%d tokens (~%.1f KB prompt)",
        estimated,
        total_chars / 1024,
    )

    groq = get_llm(model=PRIMARY_MODEL, streaming=True)

    groq_exc: Exception | None = None

    for attempt in range(_GROQ_429_MAX_RETRIES + 1):

        collected: list[str] = []

        try:

            async for chunk in groq.astream(messages):

                text = _chunk_text(chunk.content)

                if text:

                    collected.append(text)

                    yield text

            response_text = "".join(collected)

            _record_groq_token_usage(messages, response_text)

            _record_tpm(_estimate_tokens(messages) + max(1, len(response_text) // 4))

            logger.info(

                "LLM Groq stream primary %s → %.2fs",

                PRIMARY_MODEL,

                time.perf_counter() - t0,

            )

            return

        except Exception as exc:

            groq_exc = exc

            if is_llm_auth_error(exc):

                logger.warning(

                    "Groq stream auth failed after %.2fs: %s",

                    time.perf_counter() - t0,

                    exc,

                )

                yield LLM_CONNECTION_ERROR

                return

            if _is_groq_429_error(exc) and attempt < _GROQ_429_MAX_RETRIES:

                wait_seconds = _parse_groq_retry_wait_seconds(exc)

                logger.warning(

                    "Groq stream rate limited (429); retrying in %.1fs (attempt %s/%s)",

                    wait_seconds + 1,

                    attempt + 1,

                    _GROQ_429_MAX_RETRIES,

                )

                await asyncio.sleep(wait_seconds + 1)

                continue

            if not _groq_failure_allows_static_fallback(exc):

                logger.warning(

                    "Groq stream failed after %.2fs: %s",

                    time.perf_counter() - t0,

                    exc,

                )

                yield LLM_STATIC_FALLBACK

                return

            break

    logger.warning(

        "Groq stream rate limited or unavailable after %.2fs (%s); trying OpenRouter fallback.",

        time.perf_counter() - t0,

        groq_exc,

    )

    try:
        async for text in stream_openrouter_fallback(messages):
            yield text
        return
    except Exception as exc:
        logger.warning("OpenRouter stream fallback failed: %s", exc)

    try:

        async for text in stream_gemini_fallback(messages):

            yield text

        return

    except Exception as exc:

        logger.warning("Gemini fallback failed: %s", exc)

    yield LLM_STATIC_FALLBACK


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


# Condensed system prompt used only for faculty analytical intents (faculty_attendance,
# faculty_at_risk, faculty_ungraded, faculty_performance). These requests already embed a
# sizeable ERP data summary in the human message, so the full TAIA_IDENTITY_SYSTEM persona
# text is trimmed down here to keep total prompt tokens well under the Groq TPM limit.
# Every other intent keeps using TAIA_IDENTITY_SYSTEM unchanged.
TAIA_FACULTY_SYSTEM = """You are TAIA (Technify Academic AI Assistant) by Technify Software House. \
You are a bot, NOT the user. Answer the faculty member's question using ONLY the \
course/student data provided in this message. Be concise and accurate. Never reveal \
another faculty member's or another student's unrelated private data.

DATA PRESENTATION RULES (follow strictly):
1. If the data contains a list of students (e.g. under "top_at_risk_students", \
"top_low_attendance_students", or "top_ungraded_assignments"), ALWAYS present every student \
in that list as a formatted bullet or numbered list. Never suppress or skip any student.
2. For each student entry include: name, course, attendance% or grade (if available), \
and reason. If the "reason" field is empty or null, write "Reason not specified" — \
do NOT omit the student.
3. NEVER respond with "there is no information", "no data available", or any similar \
negative if student records exist in the data — even if individual fields are null.
4. If a value is null or missing, write "N/A" for that field and move on.
5. After listing all students, add one sentence summarising the total count."""


# Condensed system prompt for admin analytical intents (admin_at_risk, admin_finance_pending).
# Avoids the full TAIA_IDENTITY_SYSTEM token overhead when the human message already
# contains a dense ERP data block.
TAIA_ADMIN_SYSTEM = """You are TAIA (Technify Academic AI Assistant) by Technify Software House. \
You are a bot, NOT the user. Answer the admin's question using ONLY the provided data. \
Be concise and accurate.

DATA RULES:
1. Student or fee records live inside "summary" in the JSON data — list them all as a \
numbered list.
2. If any field is null or missing, write "N/A" for that field.
3. Never say "no information" or "no data available" when records are present in the data.
4. State the total count first, then list individual entries."""


def build_rag_prompt(query: str, chunks: list) -> str:
    """Build the admin RAG human-message prompt from hybrid-retrieved chunks."""
    if chunks:
        lines = []
        for chunk in chunks:
            if hasattr(chunk, "page_content") and hasattr(chunk, "metadata"):
                page = chunk.metadata.get("page", "N/A")
                content = chunk.page_content.strip()
                lines.append(f"[Page {page}] {content}")
            else:
                lines.append(f"- {chunk}")
        combined = "\n".join(lines)
    else:
        combined = "(no matching records retrieved)"
    return (
        "You are an AI assistant. Below are excerpts from uploaded documents.\n"
        "- Answer the user's question using only these excerpts.\n"
        "- Be concise; do not include unrelated information.\n"
        "- Always cite the page number in parentheses at the end of each factual "
        'statement, e.g., "(Page 9)".\n'
        "- If the user asks for a reference or page number, reply ONLY with the exact "
        "page number and the relevant sentence from the excerpt.\n"
        '- If the answer is not found, say "Not found in the uploaded documents."\n\n'
        f"Excerpts:\n{combined}\n\n"
        f"User question: {query}"
    )