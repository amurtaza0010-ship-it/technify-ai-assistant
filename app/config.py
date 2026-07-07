import os

from dotenv import load_dotenv



load_dotenv()



_DEFAULT_PRIMARY = "llama-3.3-70b-versatile"

_DEFAULT_FALLBACK = "openai/gpt-4o-mini"





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

    # Primary Groq model (env overrides with hardcoded default)

    LLM_PRIMARY_MODEL: str = (

        os.getenv("GROQ_PRIMARY_MODEL")

        or os.getenv("LLM_MODEL")

        or _DEFAULT_PRIMARY

    )

    # OpenRouter fallback model — LLM_FALLBACK_MODEL only (never GROQ_FALLBACK_MODEL)

    LLM_FALLBACK_MODEL: str = (

        os.getenv("LLM_FALLBACK_MODEL")

        or _DEFAULT_FALLBACK

    )

    # Backward-compatible aliases

    LLM_MAIN_MODEL: str = LLM_PRIMARY_MODEL

    LLM_MODEL: str = LLM_PRIMARY_MODEL

    # Admin RAG (hybrid search over uploaded ERP data)
    CHROMA_COLLECTION_ADMIN: str = os.getenv("CHROMA_COLLECTION_ADMIN", "admin_erp_data")
    ADMIN_RAG_PERSIST_DIR: str = os.getenv(
        "ADMIN_RAG_PERSIST_DIR",
        os.path.join(os.path.dirname(__file__), "..", "data", "admin_rag_store"),
    )
    ADMIN_BM25_INDEX_PATH: str = os.getenv(
        "ADMIN_BM25_INDEX_PATH",
        os.path.join(
            os.getenv(
                "ADMIN_RAG_PERSIST_DIR",
                os.path.join(os.path.dirname(__file__), "..", "data", "admin_rag_store"),
            ),
            "bm25_index.pkl",
        ),
    )





def get_settings():

    return Settings()

