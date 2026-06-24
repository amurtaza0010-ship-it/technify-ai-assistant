"""
TAIA - Gunicorn configuration
Runs FastAPI (app.main:app) using Uvicorn worker processes under Gunicorn.
Used by the Dockerfile's CMD: gunicorn app.main:app -c gunicorn_config.py
"""

import multiprocessing
import os

# ---- Server socket ----
bind = f"{os.getenv('APP_HOST', '0.0.0.0')}:{os.getenv('APP_PORT', '8000')}"

# ---- Worker processes ----
# Standard formula: (2 x CPU cores) + 1, capped at 4 so small
# instances/containers don't get over-subscribed.
workers = int(os.getenv("GUNICORN_WORKERS", "1"))
worker_class = "uvicorn.workers.UvicornWorker"
worker_connections = 1000
threads = 1

# ---- Timeouts ----
# Groq LLM calls + ChromaDB retrieval can take a few seconds,
# so give workers more room than the Gunicorn default (30s).
timeout = int(os.getenv("GUNICORN_TIMEOUT", 120))
graceful_timeout = 30
keepalive = 5

# ---- Reliability ----
# Do not recycle workers: each new worker reloads HuggingFace embeddings (~15s).
max_requests = 0
max_requests_jitter = 0
# Embeddings/Chroma must initialize per worker via FastAPI lifespan warmup.
preload_app = False

# ---- Logging ----
accesslog = "-"   # stdout (captured by `docker logs`)
errorlog = "-"    # stderr
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")
access_log_format = (
    '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(L)s'
)

# ---- Process naming ----
proc_name = "taia_ai_assistant"
