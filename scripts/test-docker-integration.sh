#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
export MSYS_NO_PATHCONV=1
native_path() {
  case "$(uname -s)" in MINGW*|MSYS*) cygpath -w "$1" ;; *) printf '%s\n' "$1" ;; esac
}
variant="${AGRIFOS_INTEGRATION_VARIANT:-bookworm}"
compose_files=(--file "$(native_path "$repo_root/compose.yaml")")
test_image=agrifos-backend:test
case "$variant" in
  bookworm) ;;
  trixie)
    mkdir -p .docker/evaluation
    cat > .docker/evaluation/compose-trixie.yaml <<'YAML'
services:
  api:
    image: agrifos-backend-evaluation:trixie-development
  migrate:
    image: agrifos-backend-evaluation:trixie-runtime
  integration:
    image: agrifos-backend-evaluation:trixie-test
YAML
    compose_files+=(--file "$(native_path "$repo_root/.docker/evaluation/compose-trixie.yaml")")
    test_image=agrifos-backend-evaluation:trixie-test
    for target in development runtime test; do docker image inspect "agrifos-backend-evaluation:trixie-$target" >/dev/null; done
    ;;
  *) printf 'Unsupported integration image variant.\n' >&2; exit 2 ;;
esac
compose() { docker compose --project-directory "$(native_path "$repo_root")" "${compose_files[@]}" "$@"; }
docker info >/dev/null
[[ -x .tools/supabase/supabase.exe ]] && cli=.tools/supabase/supabase.exe || cli=.tools/supabase/supabase
[[ -x "$cli" ]] || { printf 'Install the pinned local CLI first.\n' >&2; exit 1; }
if [[ "$variant" == bookworm ]]; then compose build backend-unit api migrate; fi
test_id="agrifos-it-$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')"
export AGRIFOS_ENV_DIR=".docker/integration/$test_id"
export AGRIFOS_NETWORK="$test_id"
export AGRIFOS_SUPABASE_WORKDIR="$repo_root/$AGRIFOS_ENV_DIR"
export AGRIFOS_API_PORT=8010
if [[ "$(uname -s)" != MINGW* && "$(uname -s)" != MSYS* ]]; then
  export AGRIFOS_UID="$(id -u)" AGRIFOS_GID="$(id -g)"
fi
mkdir -p "$AGRIFOS_ENV_DIR"
docker run --rm --user "${AGRIFOS_UID:-1000}:${AGRIFOS_GID:-1000}" \
  --mount "type=bind,source=$(native_path "$repo_root/supabase/config.toml"),target=/source/supabase/config.toml,readonly" \
  --mount "type=bind,source=$(native_path "$repo_root/supabase/templates"),target=/source/supabase/templates,readonly" \
  --mount "type=bind,source=$(native_path "$repo_root/docker/integration_setup.py"),target=/setup.py,readonly" \
  --mount "type=bind,source=$(native_path "$AGRIFOS_SUPABASE_WORKDIR"),target=/output" \
  "$test_image" python /setup.py "$test_id"
printf 'Isolated integration project: %s (ports 54331–54334 and API 8010).\n' "$test_id"
# Stop only this task-created project on failure; preserve volumes/evidence for investigation.
cleanup() {
  result=$?
  trap - EXIT
  if ! compose -p "$test_id" stop api migrate; then printf 'Cleanup: API stop failed; resources preserved.\n' >&2; result=1; fi
  if ! bash scripts/supabase-local.sh stop; then printf 'Cleanup: Supabase stop failed; resources preserved.\n' >&2; result=1; fi
  exit "$result"
}
trap cleanup EXIT
capture_bindings() {
  local phase="$1" item
  local containers=()
  while IFS= read -r item; do [[ -z "$item" ]] || containers+=("$item"); done < <(
    docker ps --filter "label=com.supabase.cli.project=$test_id" --format '{{.Names}}')
  item="$(compose -p "$test_id" ps -q api)"
  [[ -n "$item" ]] || { printf 'FAIL: API container is missing.\n' >&2; return 1; }
  containers+=("$item")
  docker inspect --format '{"name":{{json .Name}},"image":{{json .Image}},"requested":{{json .HostConfig.PortBindings}},"actual":{{json .NetworkSettings.Ports}}}' \
    "${containers[@]}" > "$AGRIFOS_ENV_DIR/bindings-$phase.jsonl"
  docker run --rm --network none --user "${AGRIFOS_UID:-1000}:${AGRIFOS_GID:-1000}" \
    --mount "type=bind,source=$(native_path "$AGRIFOS_SUPABASE_WORKDIR"),target=/evidence,readonly" \
    --mount "type=bind,source=$(native_path "$repo_root/docker/audit_bindings.py"),target=/audit.py,readonly" \
    "$test_image" python /audit.py "/evidence/bindings-$phase.jsonl" "$test_id"
  if [[ "$(uname -s)" == MINGW* || "$(uname -s)" == MSYS* ]]; then
    powershell.exe -NoProfile -File "$(native_path "$repo_root/docker/audit_windows_listeners.ps1")" \
      -OutputPath "$(native_path "$AGRIFOS_SUPABASE_WORKDIR/windows-listeners-$phase.json")"
  fi
}
bash scripts/supabase-local.sh start
for inherited_variable in ${!SUPABASE_@}; do unset "$inherited_variable"; done
export SUPABASE_TELEMETRY_DISABLED=1
export SUPABASE_ENV=development
"$cli" --workdir "$(native_path "$AGRIFOS_SUPABASE_WORKDIR")" status --output json | docker run --rm -i \
  --user "${AGRIFOS_UID:-1000}:${AGRIFOS_GID:-1000}" \
  --mount "type=bind,source=$(native_path "$AGRIFOS_SUPABASE_WORKDIR"),target=/output" \
  --mount "type=bind,source=$(native_path "$repo_root/docker/configure.py"),target=/configure.py,readonly" \
  "$test_image" python /configure.py --project "$test_id" --port 54331 --api-port 8010 --integration
compose -p "$test_id" up -d --wait --wait-timeout 180 api
capture_bindings initial
compose -p "$test_id" run --rm --no-deps integration python /checks/integration.py initial
compose -p "$test_id" exec -T api alembic current
migration_check_status=0
compose -p "$test_id" exec -T api alembic check || migration_check_status=$?
compose -p "$test_id" run --rm --no-deps integration python /checks/schema_check.py
compose -p "$test_id" exec -T api python -c \
  'import os; from pathlib import Path; assert os.geteuid() == 10001; status=Path("/proc/self/status").read_text(); assert "NoNewPrivs:\t1" in status; assert "CapBnd:\t0000000000000000" in status; print("PASS: API UID 10001, no-new-privileges and zero capability bound.")'
compose -p "$test_id" stop api migrate
bash scripts/supabase-local.sh stop
bash scripts/supabase-local.sh start
compose -p "$test_id" run --rm --no-deps migrate
compose -p "$test_id" up -d --wait --wait-timeout 180 api
capture_bindings persistence
compose -p "$test_id" exec -T api alembic check || migration_check_status=$?
compose -p "$test_id" run --rm --no-deps integration python /checks/schema_check.py
compose -p "$test_id" run --rm --no-deps integration python /checks/integration.py persistence
compose -p "$test_id" run --rm --no-deps integration python /checks/integration.py cleanup
if (( migration_check_status != 0 )); then
  printf 'FAIL: Alembic metadata drift check (exit %s); other integration stages above completed.\n' "$migration_check_status" >&2
  exit "$migration_check_status"
fi
printf 'PASS: isolated real Auth, migrations and persistence. Volumes retained; no reset/prune was run.\n'
