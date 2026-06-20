"""ERP Config — environment-driven settings for the external ERP integration (API-key auth)."""
import os
from dotenv import load_dotenv

load_dotenv()


class ERPConfig:
    # Falls back to the mock ERP base URL if a dedicated ERP_API_URL isn't set
    ERP_API_URL: str = os.getenv("ERP_API_URL", os.getenv("ERP_API_BASE_URL", "http://localhost:8001"))
    ERP_API_KEY: str = os.getenv("ERP_API_KEY", "")
    ERP_TIMEOUT: float = float(os.getenv("ERP_TIMEOUT", "30"))
    ERP_MAX_RETRIES: int = int(os.getenv("ERP_MAX_RETRIES", "3"))


def get_erp_config() -> ERPConfig:
    return ERPConfig()
