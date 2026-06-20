<<<<<<< HEAD
# Use official lightweight Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Prevent Python from writing pyc files and keep stdout unbuffered
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install dependencies first (for better cache layering)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose the API port
EXPOSE 8000

# Command to run the production Gunicorn server
CMD ["gunicorn", "app.main:app", "-c", "gunicorn.conf.py"]
=======
# ============================================================
# TAIA - Technify Academic AI Assistant
# Production Dockerfile (multi-stage build)
# ============================================================

# ---------------- Stage 1: Builder ----------------
# Build wheels here so the runtime image doesn't need a C/C++
# compiler (chromadb / hnswlib / tiktoken need build tools).
FROM python:3.10-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip && \
    pip wheel --no-cache-dir --wheel-dir /build/wheels -r requirements.txt


# ---------------- Stage 2: Runtime ----------------
FROM python:3.10-slim AS runtime

# libgomp1 is needed by some ML wheels (e.g. faiss/torch deps),
# curl is used for the container healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Run as a non-root user
RUN groupadd -r taia && useradd -r -g taia -m taia

WORKDIR /app

# Install the pre-built wheels from the builder stage (fast, no compiler needed)
COPY --from=builder /build/wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt && \
    rm -rf /wheels

# Copy application code
COPY . .

# Folders the app writes to at runtime (ChromaDB store + audit logs)
RUN mkdir -p data/vector_store logs && \
    chown -R taia:taia /app

USER taia

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/docs || exit 1

# Production server: Gunicorn managing Uvicorn workers
CMD ["gunicorn", "app.main:app", "-c", "gunicorn_config.py"]
>>>>>>> main
