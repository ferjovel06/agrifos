#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root/backend"

# Match the backend test environment in .github/workflows/ci.yml.
export ENV=test
export APP_DEBUG=false
export DATABASE_URL='postgresql+asyncpg://postgres:test@localhost:5432/agrifos_test'
export SUPABASE_URL='https://example.supabase.co'
export UV_HTTP_TIMEOUT="${UV_HTTP_TIMEOUT:-120}"

if ! command -v uv >/dev/null 2>&1; then
    printf 'Error: uv is not available on PATH.\n' >&2
    exit 127
fi

exec uv run --frozen python -m unittest discover -s tests -v
