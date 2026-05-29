FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_SYSTEM_PYTHON=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr libtesseract-dev \
        libgl1 libglib2.0-0 \
        curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock* ./
COPY packages ./packages
COPY services ./services
COPY cli ./cli
COPY scripts ./scripts

RUN uv pip install --system -e ./packages/common \
                              -e ./packages/ocr \
                              -e ./packages/classify \
                              -e ./packages/extract \
                              -e ./packages/route \
                              -e ./packages/store \
                              -e ./cli \
    && uv pip install --system fastapi uvicorn[standard] python-multipart pydantic-settings \
                              httpx openai pillow pytesseract numpy opencv-python-headless \
                              langdetect pygments structlog rich typer rq redis sqlalchemy \
                              alembic psycopg2-binary pyyaml itsdangerous authlib \
                              opentelemetry-api opentelemetry-sdk opentelemetry-instrumentation-fastapi \
                              opentelemetry-exporter-otlp

EXPOSE 7441
ENV APP_HOST=0.0.0.0 APP_PORT=7441
CMD ["uvicorn", "services.api.app.main:app", "--host", "0.0.0.0", "--port", "7441"]
