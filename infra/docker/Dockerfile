# Multi-stage production Dockerfile for the shotclassify API service.
#
# Stage layout:
#   builder  - installs build toolchain, resolves and pre-builds wheels into /wheels
#   runtime  - slim image, copies installed site-packages, runs as non-root,
#              ships only runtime OS deps (tesseract, libgl, libglib) and a
#              HEALTHCHECK that hits /healthz.

ARG PYTHON_VERSION=3.11
ARG APP_UID=10001
ARG APP_GID=10001

############################
# Stage 1: builder
############################
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_LINK_MODE=copy

# Build toolchain + headers needed to compile psycopg2, cryptography, bcrypt,
# pillow, opencv, etc. These do NOT ship in the runtime image.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        g++ \
        libpq-dev \
        libffi-dev \
        libssl-dev \
        libjpeg-dev \
        zlib1g-dev \
        libtesseract-dev \
        libgl1 \
        libglib2.0-0 \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /build

# Copy sources for the workspace packages so editable installs resolve.
COPY pyproject.toml ./
COPY packages ./packages
COPY services ./services
COPY cli ./cli

# Install the full runtime closure declared in the root pyproject. Using the
# root project gives us every dep that the API actually imports (auth, OTEL,
# Sentry, Prometheus, etc.) rather than a hand-maintained pip list that drifts.
RUN uv pip install --system --no-cache \
        -e ./packages/common \
        -e ./packages/ocr \
        -e ./packages/classify \
        -e ./packages/extract \
        -e ./packages/route \
        -e ./packages/store \
        -e ./cli \
    && uv pip install --system --no-cache \
        "fastapi>=0.115" \
        "uvicorn[standard]>=0.30" \
        "python-multipart>=0.0.9" \
        "pydantic>=2.7" \
        "pydantic-settings>=2.4" \
        "httpx>=0.27" \
        "openai>=1.40" \
        "pillow>=10.3" \
        "pytesseract>=0.3.10" \
        "numpy>=1.26" \
        "opencv-python-headless>=4.10" \
        "langdetect>=1.0.9" \
        "pygments>=2.18" \
        "structlog>=24.1" \
        "rich>=13.7" \
        "typer>=0.12" \
        "rq>=1.16" \
        "redis>=5.0" \
        "sqlalchemy>=2.0" \
        "alembic>=1.13" \
        "psycopg2-binary>=2.9" \
        "pyyaml>=6.0" \
        "python-jose[cryptography]>=3.3" \
        "passlib[bcrypt]>=1.7" \
        "itsdangerous>=2.2" \
        "authlib>=1.3" \
        "opentelemetry-api>=1.26" \
        "opentelemetry-sdk>=1.26" \
        "opentelemetry-instrumentation-fastapi>=0.47b0" \
        "opentelemetry-exporter-otlp>=1.26" \
        "prometheus-client>=0.20" \
        "sentry-sdk[fastapi]>=2.0"

############################
# Stage 2: runtime
############################
FROM python:${PYTHON_VERSION}-slim AS runtime

ARG APP_UID
ARG APP_GID

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=7441

# Runtime-only OS deps. No compilers, no -dev headers.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        libgl1 \
        libglib2.0-0 \
        libpq5 \
        curl \
        ca-certificates \
        tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid ${APP_GID} app \
    && useradd  --system --uid ${APP_UID} --gid ${APP_GID} \
        --home-dir /app --shell /usr/sbin/nologin app

# Copy installed Python environment from the builder stage.
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

WORKDIR /app

# Copy application source. Workspace packages are installed editable in the
# builder stage, so the source tree must be present at runtime too.
COPY --chown=app:app packages ./packages
COPY --chown=app:app services ./services
COPY --chown=app:app cli ./cli
COPY --chown=app:app pyproject.toml ./pyproject.toml

# Storage dir for local backend; mounted as a PVC in Kubernetes.
RUN mkdir -p /app/storage && chown -R app:app /app/storage

USER app:app

EXPOSE 7441

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl --silent --fail "http://127.0.0.1:${APP_PORT}/healthz" || exit 1

# tini reaps zombies and forwards signals cleanly to uvicorn workers.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "services.api.app.main:app", "--host", "0.0.0.0", "--port", "7441"]
