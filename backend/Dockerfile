# syntax=docker/dockerfile:1.7

FROM python:3.13.14-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build/backend

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

# Pin the installer copied into the runtime venv as well as application dependencies.
RUN python -m pip install --upgrade "pip==26.1.2"

COPY backend/pyproject.toml ./pyproject.toml
COPY backend/app ./app

RUN python -m pip install .


FROM builder AS development-builder

RUN python -m pip install ".[dev]"


FROM python:3.13.14-slim-bookworm AS runtime-base

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app

WORKDIR /app

COPY --chown=app:app backend/app ./app
COPY --chown=app:app backend/alembic ./alembic
COPY --chown=app:app backend/alembic.ini ./alembic.ini

RUN mkdir -p /app/media /app/configs \
    && chown -R app:app /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=3)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]


FROM runtime-base AS development

COPY --from=development-builder /opt/venv /opt/venv


FROM runtime-base AS runtime

COPY --from=builder /opt/venv /opt/venv
