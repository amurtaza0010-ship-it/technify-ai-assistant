import os

from dotenv import load_dotenv



load_dotenv()



_DEFAULT_PRIMARY = "llama-3.3-70b-versatile"

_DEFAULT_FALLBACK = "llama-3.1-8b-instant"





class Settings:

    ERP_API_BASE_URL: str = os.getenv(

        "ERP_API_BASE_URL", "http://127.0.0.1:8801/api/v1"

    )

    LLM_API_KEY: str = (

        os.getenv("GROQ_API_KEY")

        or os.getenv("LLM_API_KEY")

        or os.getenv("OPENAI_API_KEY")

    )

    LLM_BASE_URL: str = os.getenv(

        "LLM_BASE_URL",

        "https://api.groq.com/openai/v1"

        if (os.getenv("GROQ_API_KEY") or "").startswith("gsk_")

        else "https://openrouter.ai/api/v1",

    )

    # Primary / fallback Groq models (env overrides with hardcoded defaults)

    LLM_PRIMARY_MODEL: str = (

        os.getenv("GROQ_PRIMARY_MODEL")

        or os.getenv("LLM_MODEL")

        or _DEFAULT_PRIMARY

    )

    LLM_FALLBACK_MODEL: str = (

        os.getenv("GROQ_FALLBACK_MODEL")

        or os.getenv("LLM_FALLBACK_MODEL")

        or _DEFAULT_FALLBACK

    )

    # Backward-compatible aliases

    LLM_MAIN_MODEL: str = LLM_PRIMARY_MODEL

    LLM_MODEL: str = LLM_PRIMARY_MODEL





def get_settings():

    return Settings()

