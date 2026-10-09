#!/usr/bin/env bash
# Evaluation only: never changes backend/Dockerfile or normal Agrifos tags.
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$repo_root"
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'
mode="${1:-build}"
[[ $# -le 1 ]] || exit 2
native_path() { case "$(uname -s)" in MINGW*|MSYS*) cygpath -w "$1" ;; *) printf '%s\n' "$1" ;; esac; }
evaluation_dir="$repo_root/.docker/evaluation"
mkdir -p "$evaluation_dir"
[[ "$(cd "$evaluation_dir" && pwd -P)" == "$evaluation_dir" ]] || exit 1
candidate='python:3.13.16-slim-trixie@sha256:bf44cdfcb76cd3b41e879bc058fc37ec5872002ccfde7fcb765e218cde0cd79c'
case "$mode" in
  build)
    # Retain the isolated workflow after adoption; reject any unreviewed base.
    baseline='FROM python:3.13.16-slim-bookworm@sha256:a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641 AS base'
    if [[ "$(tr -d '\r' < backend/Dockerfile | grep -Fxc "$baseline")" == 1 ]]; then
      tr -d '\r' < backend/Dockerfile | sed "s#^$baseline\$#FROM $candidate AS base#" > "$evaluation_dir/Dockerfile"
    else
      [[ "$(tr -d '\r' < backend/Dockerfile | grep -Fxc "FROM $candidate AS base")" == 1 ]] || exit 1
      tr -d '\r' < backend/Dockerfile > "$evaluation_dir/Dockerfile"
    fi
    for target in test development runtime; do
      docker build --file "$(native_path "$evaluation_dir/Dockerfile")" --target "$target" \
        --tag "agrifos-backend-evaluation:trixie-$target" "$(native_path "$repo_root/backend")"
    done
    ;;
  test)
    docker run --rm --network none --env UV_NO_SYNC=1 --env UV_OFFLINE=1 \
      --mount "type=bind,source=$(native_path "$repo_root/scripts/test-backend.sh"),target=/workspace/scripts/test-backend.sh,readonly" \
      agrifos-backend-evaluation:trixie-test bash /workspace/scripts/test-backend.sh
    docker run --rm --network none agrifos-backend-evaluation:trixie-runtime python -c \
      'import sys, ssl, sqlite3, jwt, urllib3, asyncpg, psycopg2, cryptography, pydantic_core, greenlet; print(sys.version); print(ssl.OPENSSL_VERSION); print("SQLite", sqlite3.sqlite_version); print("PyJWT", jwt.__version__, "urllib3", urllib3.__version__); print("PASS: locked binary dependencies import")'
    ;;
  scan) AGRIFOS_SCAN_IMAGE=agrifos-backend-evaluation:trixie-runtime bash scripts/check-docker.sh images ;;
  integration) AGRIFOS_INTEGRATION_VARIANT=trixie bash scripts/test-docker-integration.sh ;;
  *) printf 'Usage: bash scripts/evaluate-trixie.sh build|test|scan|integration\n' >&2; exit 2 ;;
esac
