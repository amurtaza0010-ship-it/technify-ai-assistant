import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    ERP_API_BASE_URL: str = "http://localhost:8001"
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
    LLM_MODEL: str = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")

def get_settings():
    return Settings()