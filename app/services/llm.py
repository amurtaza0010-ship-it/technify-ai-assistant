"""

LLM client configuration for TAIA.

"""

import logging

import os

import re

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

        "max_retries": 0,

        "timeout": 30.0,

    }

    if max_tokens is not None:

        kwargs["max_tokens"] = max_tokens



    client = ChatOpenAI(**kwargs)

    _llm_cache[cache_key] = client

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

    """Detect rate limits anywhere in the exception chain (for outer handlers)."""

    return any(_exception_indicates_rate_limit(exc) for exc in _iter_error_chain(error))





def is_direct_rate_limit_error(error: Exception) -> bool:

    """Detect rate limits on this exception only (ignore chained primary 429)."""

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





def _configured_model_chain() -> list[str]:

    models: list[str] = []

    for model in (PRIMARY_MODEL, FALLBACK_MODEL):

        if model and model not in models:

            models.append(model)

    return models





def _max_tokens_for_chain_index(index: int) -> int | None:

    return _FALLBACK_MAX_TOKENS if index > 0 else None





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





async def ainvoke_fallback_only(messages: Sequence[BaseMessage]) -> BaseMessage:

    """Invoke configured fallback model(s) directly."""

    models = _configured_model_chain()

    if len(models) <= 1:

        return await ainvoke_llm_with_fallback(messages)

    return await _ainvoke_model_chain(messages, models[1:])





async def astream_fallback_only(

    messages: Sequence[BaseMessage],

) -> AsyncIterator[str]:

    """Stream configured fallback model(s) directly."""

    models = _configured_model_chain()

    if len(models) <= 1:

        async for chunk in astream_llm_with_fallback(messages):

            yield chunk

        return

    async for chunk in _astream_model_chain(messages, models[1:]):

        yield chunk





async def _ainvoke_model_chain(

    messages: Sequence[BaseMessage],

    models: list[str],

) -> BaseMessage:

    for index, model in enumerate(models):

        t0 = time.perf_counter()

        llm = get_llm(model=model, max_tokens=_FALLBACK_MAX_TOKENS)

        try:

            result = await llm.ainvoke(messages)

            logger.info("Fallback model succeeded.")

            logger.info(

                "LLM fallback %s → %.2fs",

                model,

                time.perf_counter() - t0,

            )

            return result

        except Exception as exc:

            if not is_direct_rate_limit_error(exc):

                logger.warning(

                    "LLM %s failed (non-rate-limit) after %.2fs: %s",

                    model,

                    time.perf_counter() - t0,

                    exc,

                )

                raise

            if index < len(models) - 1:

                logger.warning(

                    "Primary model rate limited. Switching to fallback model.",

                )

                continue

            logger.warning("Fallback model failed. Returning busy message.")

            return AIMessage(content=LLM_RATE_LIMIT_BUSY)

    logger.warning("Fallback model failed. Returning busy message.")

    return AIMessage(content=LLM_RATE_LIMIT_BUSY)





async def _astream_model_chain(

    messages: Sequence[BaseMessage],

    models: list[str],

) -> AsyncIterator[str]:

    for index, model in enumerate(models):

        t0 = time.perf_counter()

        llm = get_llm(

            model=model,

            max_tokens=_FALLBACK_MAX_TOKENS,

            streaming=True,

        )

        try:

            async for chunk in llm.astream(messages):

                text = _chunk_text(chunk.content)

                if text:

                    yield text

            logger.info("Fallback model succeeded.")

            logger.info(

                "LLM stream fallback %s → %.2fs",

                model,

                time.perf_counter() - t0,

            )

            return

        except Exception as exc:

            if not is_direct_rate_limit_error(exc):

                logger.warning(

                    "LLM stream %s failed (non-rate-limit) after %.2fs: %s",

                    model,

                    time.perf_counter() - t0,

                    exc,

                )

                raise

            if index < len(models) - 1:

                logger.warning(

                    "Primary model rate limited. Switching to fallback model.",

                )

                continue

            logger.warning("Fallback model failed. Returning busy message.")

            yield LLM_RATE_LIMIT_BUSY

            return

    logger.warning("Fallback model failed. Returning busy message.")

    yield LLM_RATE_LIMIT_BUSY





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

    Invoke configured models in order. On direct HTTP 429 for a model, try the next.

    Return LLM_RATE_LIMIT_BUSY only after every configured model is rate limited.

    """

    models = _configured_model_chain()

    for index, model in enumerate(models):

        t0 = time.perf_counter()

        llm = get_llm(model=model, max_tokens=_max_tokens_for_chain_index(index))

        try:

            result = await llm.ainvoke(messages)

            if index == 0:

                logger.info(

                    "LLM primary %s → %.2fs",

                    model,

                    time.perf_counter() - t0,

                )

            else:

                logger.info("Fallback model succeeded.")

                logger.info(

                    "LLM fallback %s → %.2fs",

                    model,

                    time.perf_counter() - t0,

                )

            return result

        except Exception as exc:

            elapsed = time.perf_counter() - t0

            if not is_direct_rate_limit_error(exc):

                logger.warning(

                    "LLM %s failed (non-rate-limit) after %.2fs: %s",

                    model,

                    elapsed,

                    exc,

                )

                raise

            if index < len(models) - 1:

                logger.warning(

                    "Primary model rate limited. Switching to fallback model.",

                )

                continue

            logger.warning("Fallback model failed. Returning busy message.")

            return AIMessage(content=LLM_RATE_LIMIT_BUSY)

    logger.warning("Fallback model failed. Returning busy message.")

    return AIMessage(content=LLM_RATE_LIMIT_BUSY)





async def astream_llm_with_fallback(

    messages: Sequence[BaseMessage],

) -> AsyncIterator[str]:

    """

    Stream configured models in order. On direct HTTP 429, continue with fallback stream.

    Yield LLM_RATE_LIMIT_BUSY only after every configured model is rate limited.

    """

    models = _configured_model_chain()

    for index, model in enumerate(models):

        t0 = time.perf_counter()

        llm = get_llm(

            model=model,

            max_tokens=_max_tokens_for_chain_index(index),

            streaming=True,

        )

        try:

            async for chunk in llm.astream(messages):

                text = _chunk_text(chunk.content)

                if text:

                    yield text

            if index == 0:

                logger.info(

                    "LLM stream primary %s → %.2fs",

                    model,

                    time.perf_counter() - t0,

                )

            else:

                logger.info("Fallback model succeeded.")

                logger.info(

                    "LLM stream fallback %s → %.2fs",

                    model,

                    time.perf_counter() - t0,

                )

            return

        except Exception as exc:

            elapsed = time.perf_counter() - t0

            if not is_direct_rate_limit_error(exc):

                logger.warning(

                    "LLM stream %s failed (non-rate-limit) after %.2fs: %s",

                    model,

                    elapsed,

                    exc,

                )

                raise

            if index < len(models) - 1:

                logger.warning(

                    "Primary model rate limited. Switching to fallback model.",

                )

                continue

            logger.warning("Fallback model failed. Returning busy message.")

            yield LLM_RATE_LIMIT_BUSY

            return

    logger.warning("Fallback model failed. Returning busy message.")

    yield LLM_RATE_LIMIT_BUSY





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


