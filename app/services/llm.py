"""
LLM client configuration for TAIA.

Resolves API keys from .env (GROQ_API_KEY, LLM_API_KEY, OPENAI_API_KEY)
and builds a LangChain ChatOpenAI client pointed at the correct provider.
"""
import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

LLM_CONNECTION_ERROR = (
    "I couldn't connect to the AI service. Please check the backend logs "
    "to ensure the API key is valid."
)

_KEY_ENV_VARS = ("GROQ_API_KEY", "LLM_API_KEY", "OPENAI_API_KEY")


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
    """Log whether an LLM API key is present at runtime."""
    groq_api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not groq_api_key:
        resolved = _resolve_api_key()
        if not resolved:
            print("CRITICAL ERROR: GROQ_API_KEY is empty or missing from .env file!")
            return False
        print(
            f"DEBUG: LLM API key loaded via fallback env var "
            f"(starts with: {resolved[:10]}...)"
        )
        return True

    print(
        f"DEBUG: GROQ_API_KEY loaded successfully "
        f"(starts with: {groq_api_key[:10]}...)"
    )
    return True


def get_llm() -> ChatOpenAI:
    """Return a configured LangChain ChatOpenAI client."""
    if not check_llm_api_key():
        raise ValueError("LLM API key is not configured")

    api_key = _resolve_api_key()
    if not api_key:
        raise ValueError("LLM API key is not configured")

    return ChatOpenAI(
        api_key=api_key,
        base_url=_resolve_base_url(api_key),
        model=os.getenv("LLM_MODEL", "llama-3.3-70b-versatile"),
        temperature=float(os.getenv("LLM_TEMPERATURE", "0.3")),
    )


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
