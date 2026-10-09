FROM python:3.13-slim-trixie AS base

RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app

FROM base AS dependencies
COPY --from=ghcr.io/astral-sh/uv:0.12.2 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project

FROM base AS runtime
RUN useradd --uid 10001 --create-home agrifos
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
