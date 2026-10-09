#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"
task="${1:-version}"
if (( $# > 0 )); then shift; fi

case "$task" in
  version|restore|analyze|test) service=flutter-tools ;;
  licenses|sdk|apk) service=flutter-android ;;
  *)
    printf 'Usage: bash scripts/flutter-container.sh {version|restore|analyze|test|licenses|sdk|apk}\n' >&2
    exit 2
    ;;
esac
if [[ "$task" == licenses && ! -t 0 ]]; then
  printf 'Run the licenses task yourself in an interactive terminal to review Android SDK terms.\n' >&2
  exit 2
fi
if [[ "$task" == apk ]]; then
  if [[ -z "${AGRIFOS_CLIENT_ENV:-}" && -f "$repo_root/.docker/local/client.env" ]]; then
    export AGRIFOS_CLIENT_ENV=.docker/local/client.env
  fi
  if [[ -z "${AGRIFOS_CLIENT_ENV:-}" || ! -f "$repo_root/$AGRIFOS_CLIENT_ENV" ]]; then
    printf 'Prepare .docker/local/client.env or set AGRIFOS_CLIENT_ENV to a repository-relative public client env file before building an APK.\n' >&2
    exit 2
  fi
fi
mkdir -p "$repo_root/artifacts"

# Docker Desktop needs Windows paths for the Compose file. Disable MSYS path
# rewriting for container arguments after converting the two host paths.
compose_file="$repo_root/compose.yaml"
case "${OSTYPE:-}" in
  msys*|cygwin*)
    compose_file="$(cygpath -w "$compose_file")"
    repo_root="$(cygpath -w "$repo_root")"
    export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'
    export AGRIFOS_UID="${AGRIFOS_UID:-1000}" AGRIFOS_GID="${AGRIFOS_GID:-1000}"
    ;;
  *)
    export AGRIFOS_UID="${AGRIFOS_UID:-$(id -u)}" AGRIFOS_GID="${AGRIFOS_GID:-$(id -g)}"
    ;;
esac

# Cached construction also applies the caller's UID/GID to the image on first
# use. Existing named volumes retain their owner; use a separate Compose
# project namespace when changing the mapped UID/GID.
run_options=(--rm --no-deps --build)
if [[ "$task" != licenses ]]; then run_options+=(-T); fi
exec docker compose --project-directory "$repo_root" --file "$compose_file" \
  run "${run_options[@]}" "$service" "$task" "$@"
