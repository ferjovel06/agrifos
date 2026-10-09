#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
export MSYS_NO_PATHCONV=1
native_path() {
  case "$(uname -s)" in MINGW*|MSYS*) cygpath -w "$1" ;; *) printf '%s\n' "$1" ;; esac
}
case "$(uname -s)" in
  MINGW*|MSYS*) ;;
  *) export AGRIFOS_UID="${AGRIFOS_UID:-$(id -u)}" AGRIFOS_GID="${AGRIFOS_GID:-$(id -g)}" ;;
esac
command_name="${1:-help}"
case "$command_name" in
  check)
    docker version
    docker compose version
    docker compose config --quiet
    bash scripts/supabase-local.sh check
    ;;
  prepare)
    mkdir -p .docker/local artifacts
    docker compose config --quiet
    printf 'Prepared local directories. Flutter tests use docker/client.env.example by default.\n'
    ;;
  build)
    docker compose build backend-unit migrate api
    ;;
  configure)
    [[ -f .tools/supabase/supabase.exe ]] && cli=.tools/supabase/supabase.exe || cli=.tools/supabase/supabase
    [[ -x "$cli" ]] || { printf 'Run bash scripts/install-supabase.sh first.\n' >&2; exit 1; }
    mkdir -p .docker/local artifacts
    bash scripts/supabase-local.sh check
    # The CLI also reads root .env; preserve that file and refuse ambiguous input.
    [[ ! -e .env ]] || { printf 'Preserve root .env and use an isolated checkout for local Supabase.\n' >&2; exit 1; }
    for inherited_variable in ${!SUPABASE_@}; do unset "$inherited_variable"; done
    export SUPABASE_TELEMETRY_DISABLED=1
    export SUPABASE_ENV=development
    # No shell argument or log contains the JSON credentials.
    "$cli" --workdir "$(native_path "$repo_root")" status --output json | docker run --rm -i \
      --user "${AGRIFOS_UID:-1000}:${AGRIFOS_GID:-1000}" \
      --mount "type=bind,source=$(native_path "$repo_root/.docker/local"),target=/output" \
      --mount "type=bind,source=$(native_path "$repo_root/docker/configure.py"),target=/configure.py,readonly" \
      agrifos-backend:test python /configure.py
    ;;
  up)
    [[ -f .docker/local/backend.env ]] || { printf 'Run configure after starting Supabase.\n' >&2; exit 1; }
    docker compose up -d --wait --wait-timeout 180 api
    ;;
  migrate)
    [[ -f .docker/local/backend.env ]] || { printf 'Local backend.env is missing.\n' >&2; exit 1; }
    docker compose run --rm --no-deps migrate
    ;;
  test)
    docker compose run --build --rm --no-deps backend-unit
    ;;
  stop) docker compose stop api api-runtime migrate ;;
  logs) docker compose logs --tail 100 api migrate ;;
  health)
    docker compose exec -T api python -c 'import urllib.request; [print(path, urllib.request.urlopen("http://127.0.0.1:8000" + path, timeout=5).status) for path in ("/health", "/health/db")]'
    ;;
  *) printf 'Usage: bash scripts/docker-dev.sh check|prepare|build|configure|up|migrate|test|stop|logs|health\n' ;;
esac
