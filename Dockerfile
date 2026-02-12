# Stage 1: Builder — install all Python dependencies
FROM python:3.11-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml README.md ./
COPY pdf2md/ pdf2md/
COPY service/ service/
COPY migrations/ migrations/
COPY alembic.ini .
COPY scripts/ scripts/

# Create venv and install all deps (docling + agent + service)
RUN uv venv /app/.venv && \
    VIRTUAL_ENV=/app/.venv uv pip install ".[docling,agent,service]"


# Stage 2: Runtime — slim image with only what's needed
FROM python:3.11-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy venv from builder
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
ENV VIRTUAL_ENV="/app/.venv"

# Copy application source
COPY --from=builder /app/pdf2md pdf2md/
COPY --from=builder /app/service service/
COPY --from=builder /app/migrations migrations/
COPY --from=builder /app/alembic.ini .
COPY --from=builder /app/scripts scripts/
COPY --from=builder /app/pyproject.toml .

# Create data directories
RUN mkdir -p /data/uploads

EXPOSE 8000

# Default: run the API server
CMD ["uvicorn", "service.app:app", "--host", "0.0.0.0", "--port", "8000"]
