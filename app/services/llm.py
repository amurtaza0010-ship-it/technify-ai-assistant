"""

LLM client configuration for TAIA.

"""

import asyncio

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



LLM_STATIC_FALLBACK = (

    "AI temporarily busy, showing fallback response."

)



LLM_OPENROUTER_PAYMENT_ERROR = (

    "The AI service is temporarily unavailable due to token limits. "

    "Please try reducing your request or topping up the OpenRouter credits."

)



STATIC_FALLBACK_SOURCE = "static_fallback"



_OPENROUTER_SAFETY_MODEL = "openai/gpt-4o-mini"



_KEY_ENV_VARS = ("GROQ_API_KEY", "LLM_API_KEY", "OPENAI_API_KEY")

_FALLBACK_MAX_TOKENS = int(os.getenv("LLM_FALLBACK_MAX_TOKENS", "512"))

_GROQ_429_MAX_RETRIES = int(os.getenv("GROQ_429_MAX_RETRIES", "2"))

_GROQ_429_RETRY_DELAY = float(os.getenv("GROQ_429_RETRY_DELAY_SECONDS", "2"))



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





def _resolve_credentials_for_model(model: str) -> tuple[str, str]:

    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()

    if (

        _uses_openrouter(model)

        and openrouter_key

    ):

        return (

            openrouter_key,

            os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),

        )



    api_key = _resolve_api_key()

    if not api_key:

        raise ValueError("LLM API key is not configured")



    return api_key, _resolve_base_url(api_key)





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



    resolved_model = model or PRIMARY_MODEL

    cache_key = (resolved_model, max_tokens, streaming)

    if cache_key in _llm_cache:

        return _llm_cache[cache_key]



    api_key, base_url = _resolve_credentials_for_model(resolved_model)



    kwargs: dict = {

        "api_key": api_key,

        "base_url": base_url,

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





def _uses_openrouter(model: str) -> bool:

    return model == _OPENROUTER_SAFETY_MODEL





def _static_fallback_payload() -> dict[str, str]:

    return {

        "text": LLM_STATIC_FALLBACK,

        "source": STATIC_FALLBACK_SOURCE,

    }





def _static_fallback_message() -> AIMessage:

    return AIMessage(

        content=LLM_STATIC_FALLBACK,

        additional_kwargs=_static_fallback_payload(),

    )





def _groq_failure_allows_fallback(exc: Exception) -> bool:

    return is_direct_rate_limit_error(exc)





def _exception_status_code(error: Exception) -> int | None:

    status_code = getattr(error, "status_code", None)

    if status_code is not None:

        return int(status_code)



    response = getattr(error, "response", None)

    if response is not None:

        response_status = getattr(response, "status_code", None)

        if response_status is not None:

            return int(response_status)



    return None





def is_openrouter_payment_error(error: Exception) -> bool:

    if _exception_status_code(error) == 402:

        return True



    message = str(error).lower()

    return "payment required" in message or "can only afford" in message





def _openrouter_payment_fallback_message() -> AIMessage:

    return AIMessage(content=LLM_OPENROUTER_PAYMENT_ERROR)





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





async def ainvoke_classifier_llm(messages: Sequence[BaseMessage]) -> BaseMessage:

    """Intent routing is heuristic-only; never call an LLM for classification."""

    return AIMessage(content="general")





async def ainvoke_llm_with_fallback(

    messages: Sequence[BaseMessage],

) -> BaseMessage:

    """

    One Groq call, then at most one OpenRouter call, then static fallback.

    """

    t0 = time.perf_counter()

    primary_exc: Exception | None = None

    for attempt in range(_GROQ_429_MAX_RETRIES + 1):

        primary = get_llm(model=PRIMARY_MODEL)

        try:

            result = await primary.ainvoke(messages)

            logger.info(

                "LLM primary %s → %.2fs",

                PRIMARY_MODEL,

                time.perf_counter() - t0,

            )

            return result

        except Exception as exc:

            primary_exc = exc

            if is_llm_auth_error(exc):

                raise

            if is_direct_rate_limit_error(exc) and attempt < _GROQ_429_MAX_RETRIES:

                logger.warning(

                    "Groq rate limited (429); retrying in %.1fs (attempt %s/%s)",

                    _GROQ_429_RETRY_DELAY,

                    attempt + 1,

                    _GROQ_429_MAX_RETRIES + 1,

                )

                await asyncio.sleep(_GROQ_429_RETRY_DELAY)

                continue

            break

    if primary_exc is not None:

        elapsed = time.perf_counter() - t0

        if not _groq_failure_allows_fallback(primary_exc):

            logger.warning(

                "LLM primary %s failed after %.2fs: %s",

                PRIMARY_MODEL,

                elapsed,

                primary_exc,

            )

            raise primary_exc

        logger.warning("Primary model rate limited. Switching to fallback model.")



    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()

    if not openrouter_key:

        logger.warning("OpenRouter not configured. Returning static fallback.")

        return _static_fallback_message()



    t1 = time.perf_counter()

    fallback = get_llm(model=_OPENROUTER_SAFETY_MODEL, max_tokens=_FALLBACK_MAX_TOKENS)

    try:

        result = await fallback.ainvoke(messages)

        logger.info("Fallback model succeeded.")

        logger.info(

            "LLM fallback %s â†’ %.2fs",

            _OPENROUTER_SAFETY_MODEL,

            time.perf_counter() - t1,

        )

        return result

    except Exception as fallback_exc:

        if is_openrouter_payment_error(fallback_exc):

            logger.warning(

                "OpenRouter returned 402 Payment Required after %.2fs: %s",

                time.perf_counter() - t1,

                fallback_exc,

            )

            return _openrouter_payment_fallback_message()

        logger.warning(

            "OpenRouter fallback failed after %.2fs: %s",

            time.perf_counter() - t1,

            fallback_exc,

        )

        logger.warning("Fallback model failed. Returning static fallback.")

        return _static_fallback_message()





async def astream_llm_with_fallback(

    messages: Sequence[BaseMessage],

) -> AsyncIterator[str]:

    """

    One Groq stream, then at most one OpenRouter stream, then static fallback.

    Never raise to the caller.

    """

    try:

        t0 = time.perf_counter()

        primary_exc: Exception | None = None

        for attempt in range(_GROQ_429_MAX_RETRIES + 1):

            primary = get_llm(model=PRIMARY_MODEL, streaming=True)

            try:

                async for chunk in primary.astream(messages):

                    text = _chunk_text(chunk.content)

                    if text:

                        yield text

                logger.info(

                    "LLM stream primary %s → %.2fs",

                    PRIMARY_MODEL,

                    time.perf_counter() - t0,

                )

                return

            except Exception as exc:

                primary_exc = exc

                if is_direct_rate_limit_error(exc) and attempt < _GROQ_429_MAX_RETRIES:

                    logger.warning(

                        "Groq stream rate limited (429); retrying in %.1fs (attempt %s/%s)",

                        _GROQ_429_RETRY_DELAY,

                        attempt + 1,

                        _GROQ_429_MAX_RETRIES + 1,

                    )

                    await asyncio.sleep(_GROQ_429_RETRY_DELAY)

                    continue

                break

        if primary_exc is not None:

            if not _groq_failure_allows_fallback(primary_exc):

                logger.warning(

                    "LLM stream primary failed after %.2fs: %s",

                    time.perf_counter() - t0,

                    primary_exc,

                )

                yield LLM_STATIC_FALLBACK

                return

            logger.warning("Primary model rate limited. Switching to fallback model.")



        openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()

        if not openrouter_key:

            yield LLM_STATIC_FALLBACK

            return



        t1 = time.perf_counter()

        fallback = get_llm(

            model=_OPENROUTER_SAFETY_MODEL,

            max_tokens=_FALLBACK_MAX_TOKENS,

            streaming=True,

        )

        try:

            async for chunk in fallback.astream(messages):

                text = _chunk_text(chunk.content)

                if text:

                    yield text

            logger.info("Fallback model succeeded.")

            logger.info(

                "LLM stream fallback %s â†’ %.2fs",

                _OPENROUTER_SAFETY_MODEL,

                time.perf_counter() - t1,

            )

            return

        except Exception as fallback_exc:

            if is_openrouter_payment_error(fallback_exc):

                logger.warning(

                    "OpenRouter stream returned 402 Payment Required after %.2fs: %s",

                    time.perf_counter() - t1,

                    fallback_exc,

                )

                yield LLM_OPENROUTER_PAYMENT_ERROR

                return

            logger.warning(

                "OpenRouter stream fallback failed after %.2fs: %s",

                time.perf_counter() - t1,

                fallback_exc,

            )

            yield LLM_STATIC_FALLBACK

    except Exception as exc:

        logger.warning(

            "LLM stream pipeline failed; returning static fallback: %s",

            exc,

        )

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

1. You are TAIA â€” the AI assistant. You are NOT the user.

2. Never confuse yourself with the logged-in user. Never say you are the user or use the user's name as your own.

3. When the user asks about YOU ("Who are you?", "Tell me about yourself", "What is your name?" meaning the bot), answer ONLY what was asked â€” do not volunteer a full introduction unless they explicitly request one.

4. When the user asks about THEMSELVES ("Who am I?", "What is my name?", "What is my profile?"), their session data will be provided separately in that turn only â€” use it then, not otherwise.

5. Be polite, professional, and accurate. Never reveal one user's data to another user.

"""
