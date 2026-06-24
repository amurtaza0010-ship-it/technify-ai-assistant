"""Mock ERP Server — simulates the Laravel ERP backend for development.
Run with: uvicorn mock_erp.main:app --port 8801 --reload
"""
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mock_erp.routes import router

load_dotenv()


def _parse_cors_origins() -> list[str]:
    if os.getenv("CORS_ALLOW_ALL", "true").lower() in ("1", "true", "yes"):
        return ["*"]
    raw = os.getenv(
        "CORS_ORIGINS",
        "http://127.0.0.1:5000,http://localhost:5000",
    )
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


app = FastAPI(title="Mock Technify ERP", version="1.0.0", docs_url="/docs")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix="/api/v1")


@app.on_event("startup")
def preload_mock_erp_data():
    from mock_erp.routes import warmup_cache

    warmup_cache()


@app.get("/")
def root():
    return {"service": "Mock Technify ERP", "status": "running"}
