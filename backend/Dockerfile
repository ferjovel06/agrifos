FROM ghcr.io/astral-sh/uv:0.12.2@sha256:069a51314a7bb6031777a9273205fe1b0b19e914ef418207d1338b268df641dd AS uv-binary

FROM python:3.13.16-slim-trixie@sha256:bf44cdfcb76cd3b41e879bc058fc37ec5872002ccfde7fcb765e218cde0cd79c AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_DEBUG=false \
    PATH="/opt/venv/bin:$PATH"

RUN groupadd --gid 10001 agrifos \
    && useradd --uid 10001 --gid agrifos --create-home agrifos

WORKDIR /workspace/backend
EXPOSE 8000

FROM base AS dependencies

COPY --from=uv-binary /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy

# This is a virtual uv project: install locked dependencies before copying code.
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

FROM base AS development

COPY --from=dependencies /opt/venv /opt/venv
COPY --from=uv-binary /uv /usr/local/bin/uv
ENV ENV=development \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_NO_SYNC=1 \
    UV_CACHE_DIR=/home/agrifos/.cache/uv

COPY --chown=agrifos:agrifos pyproject.toml uv.lock .python-version alembic.ini ./
COPY --chown=agrifos:agrifos app ./app
COPY --chown=agrifos:agrifos alembic ./alembic

USER agrifos
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--reload-dir", "app"]

FROM development AS test

ENV ENV=test
COPY --chown=agrifos:agrifos tests ./tests
CMD ["uv", "run", "--no-sync", "python", "-m", "unittest", "discover", "-s", "tests", "-v"]

FROM base AS runtime

ENV ENV=production
# APT verifies the dependency graph; the API and migrations do not mount filesystems.
# Keep dpkg's inventory intact and preserve essential packages and Python libraries.
RUN apt-get purge --yes mount
# The base interpreter's pip vendors are not needed by the isolated app venv.
RUN /usr/local/bin/python -m pip uninstall --yes pip
COPY --from=dependencies /opt/venv /opt/venv
COPY --chown=agrifos:agrifos alembic.ini ./
COPY --chown=agrifos:agrifos app ./app
COPY --chown=agrifos:agrifos alembic ./alembic

USER agrifos
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
