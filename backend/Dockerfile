FROM python:3.13-alpine AS base

RUN apk upgrade --no-cache && apk add --no-cache libpq
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app

FROM base AS dependencies
RUN apk add --no-cache build-base postgresql-dev
COPY --from=ghcr.io/astral-sh/uv:0.12.2 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project

FROM base AS runtime
# Installation tools belong to the build stage, not the application runtime.
RUN python -m pip uninstall -y pip \
    && rm -rf /usr/local/lib/python3.13/ensurepip \
    && addgroup -g 10001 agrifos \
    && adduser -D -u 10001 -G agrifos agrifos
COPY --from=dependencies /app/.venv /app/.venv
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
USER agrifos
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS test
COPY tests ./tests
ENV ENV=test \
    APP_DEBUG=false \
    DATABASE_URL=postgresql+asyncpg://postgres:test@localhost:5432/agrifos_test \
    SUPABASE_URL=https://example.supabase.co
CMD ["python", "-m", "unittest", "discover", "-s", "tests", "-v"]
