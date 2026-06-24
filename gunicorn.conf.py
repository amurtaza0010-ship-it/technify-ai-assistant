""" 
Gunicorn Production Configuration for TAIA FastAPI Gateway. 
Usage: gunicorn app.main:app -c gunicorn.conf.py 
""" 
import multiprocessing
import os
 
# ── Server Socket ───────────────────────────────────────────────────────────────────────── 
 
bind    = "0.0.0.0:8000" 
backlog = 2048 
 
# ── Worker Processes ───────────────────────────────────────────────────────────── 
# Rule: (2 × CPU cores) + 1 
workers     = int(os.getenv("GUNICORN_WORKERS", "1"))
worker_class = "uvicorn.workers.UvicornWorker" 
threads     = 2 
timeout     = 120 
keepalive   = 5
# Avoid recycling workers — each recycle reloads HuggingFace embeddings (~15s).
max_requests = 0
max_requests_jitter = 0
# ML models must init per worker after fork; lifespan warmup handles Chroma.
preload_app = False
 
# ── Logging ─────────────────────────────────────────────────────────────────────────── 
accesslog  = "-"      # stdout 
errorlog   = "-"      # stderr 
loglevel   = "info" 
 
# ── Lifecycle Hooks ───────────────────────────────────────────────────────────── 
 
def on_starting(server): 
    print("=" * 50) 
    print("TAIA Production Server Starting (Gunicorn)") 
    print(f"Workers: {workers}") 
    print("=" * 50) 
 
def worker_exit(server, worker): 
    print(f"Worker {worker.pid} exited")