#!/usr/bin/env bash
set -euo pipefail
umask 077

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
version='2.120.0'
command_name="${1:-check}"
studio=false
confirmed_project=''
if [[ $# -gt 0 ]]; then shift; fi
if [[ "$command_name" == destroy-test ]]; then
    [[ $# -eq 2 && "$1" == --confirm-project ]] || { printf 'Usage: bash scripts/supabase-local.sh destroy-test --confirm-project agrifos-it-<8hex>\n' >&2; exit 2; }
    confirmed_project="$2"
    shift 2
elif [[ "${1:-}" == '--studio' ]]; then studio=true; shift; fi
[[ $# -eq 0 ]] || { printf 'Usage: bash scripts/supabase-local.sh check|preflight|start|stop|status [--studio]\n' >&2; exit 2; }
case "$command_name" in check|preflight|start|stop|status|destroy-test) ;; *) printf 'Unknown Supabase command.\n' >&2; exit 2 ;; esac

fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }
for tool in docker curl timeout awk sha256sum; do
    command -v "$tool" >/dev/null 2>&1 || fail "$tool is required."
done
windows=false
case "$(uname -s):$(uname -m)" in
    Linux:x86_64) cli="$repo_root/.tools/supabase/supabase" ;;
    MINGW*:x86_64|MSYS*:x86_64) windows=true; cli="$repo_root/.tools/supabase/supabase.exe" ;;
    *) fail 'Supported hosts: Linux x86_64 or Windows x64 with Git Bash.' ;;
esac
[[ -x "$cli" ]] || fail 'Run bash scripts/install-supabase.sh first.'

native_path() {
    if "$windows"; then cygpath -w "$1"; else printf '%s\n' "$1"; fi
}
normalized_path() {
    if "$windows"; then printf '%s' "$1" | tr '\\' '/' | tr '[:upper:]' '[:lower:]';
    else printf '%s' "$1"; fi
}

workdir="$(cd -- "${AGRIFOS_SUPABASE_WORKDIR:-$repo_root}" && pwd -P)"
if [[ "$workdir" != "$repo_root" ]]; then
    [[ "$workdir" == "$repo_root/.docker/integration/"* ]] ||
        fail 'Integration workdir must resolve inside this repository .docker/integration/ directory.'
fi
config="$workdir/supabase/config.toml"
[[ -f "$config" ]] || fail 'Supabase config.toml is missing.'
for dotenv_dir in "$workdir" "$workdir/supabase"; do
    for dotenv_name in .env .env.local .env.development .env.development.local; do
        [[ ! -e "$dotenv_dir/$dotenv_name" ]] || fail "A CLI dotenv file exists at $dotenv_dir/$dotenv_name; preserve it. Local scripts use .docker/local env files and refuse dotenv overrides."
    done
done
config_value() {
    awk -v section="$1" -v key="$2" '
        /^[[:space:]]*\[/ { current=$0; gsub(/^[[:space:]]*\[|\][[:space:]]*$/, "", current) }
        current == section && $0 ~ "^[[:space:]]*" key "[[:space:]]*=" {
            value=$0; sub(/^[^=]*=[[:space:]]*/, "", value); sub(/[[:space:]]*#.*/, "", value)
            gsub(/^[[:space:]]*"|"[[:space:]]*$|[[:space:]]*$/, "", value); print value; exit
        }
    ' "$config"
}
project_id="$(config_value '' project_id)"
api_port="$(config_value api port)"
db_port="$(config_value db port)"
mail_port="$(config_value local_smtp port)"
studio_port="$(config_value studio port)"
for port in "$api_port" "$db_port" "$mail_port" "$studio_port"; do
    [[ "$port" =~ ^[0-9]+$ && "$port" -ge 1024 && "$port" -le 65535 ]] || fail 'Invalid local port in config.toml.'
done
if [[ "$workdir" == "$repo_root" ]]; then
    [[ "$project_id" == agrifos ]] || fail 'Default local project_id must remain agrifos.'
    network="${AGRIFOS_NETWORK:-agrifos-local}"
    [[ "$network" == agrifos-local ]] || fail 'Default project must use agrifos-local network.'
else
    [[ "$project_id" =~ ^agrifos-it-[0-9a-f]{8}$ ]] || fail 'Integration project_id must be agrifos-it-<8 lowercase hex characters>.'
    network="${AGRIFOS_NETWORK:-$project_id}"
    [[ "$network" == "$project_id" ]] || fail 'Integration network must match its isolated project_id.'
fi
if [[ "$command_name" == destroy-test ]]; then
    [[ "$workdir" != "$repo_root" && "$confirmed_project" == "$project_id" ]] ||
        fail 'Destructive reset is only allowed for the isolated integration project named explicitly in --confirm-project; agrifos is always rejected.'
fi
api_url="http://127.0.0.1:$api_port"
expected_issuer="$api_url/auth/v1"
[[ "$(config_value auth external_url)" == "$expected_issuer" && \
   "$(config_value auth jwt_issuer)" == "$expected_issuer" ]] || fail 'Auth external_url and jwt_issuer must equal the public loopback Auth URL.'
[[ "$(config_value auth signing_keys_path)" == './.local/signing-keys.json' ]] || fail 'Auth signing_keys_path must remain ./.local/signing-keys.json for isolated local generation.'
state_dir="$workdir/supabase/.local"
key_file="$state_dir/signing-keys.json"
owner_file="$state_dir/docker-owner"
owner_description="$(printf 'version=%s\nproject=%s\nnetwork=%s\nworkdir=%s\napi_port=%s\ndb_port=%s\nmail_port=%s\nstudio_port=%s' \
    "$version" "$project_id" "$network" "$workdir" "$api_port" "$db_port" "$mail_port" "$studio_port")"

# Clear inherited Supabase credentials and overrides without reading or printing their values.
for supabase_var in "${!SUPABASE_@}"; do unset "$supabase_var"; done
# Set only local coordinates explicitly; ambient Supabase overrides must not redirect this task.
export SUPABASE_TELEMETRY_DISABLED=1
export SUPABASE_ENV=development
export SUPABASE_PROJECT_ID="$project_id"
export SUPABASE_API_PORT="$api_port"
export SUPABASE_API_EXTERNAL_URL="$api_url"
export SUPABASE_DB_PORT="$db_port"
export SUPABASE_LOCAL_SMTP_PORT="$mail_port"
export SUPABASE_STUDIO_PORT="$studio_port"
export SUPABASE_SERVICES_HOSTNAME=127.0.0.1
export SUPABASE_AUTH_EXTERNAL_URL="$expected_issuer"
export SUPABASE_AUTH_JWT_ISSUER="$expected_issuer"
export SUPABASE_AUTH_SIGNING_KEYS_PATH="$(native_path "$key_file")"
export SUPABASE_AUTH_MFA_TOTP_ENROLL_ENABLED=true
export SUPABASE_AUTH_MFA_TOTP_VERIFY_ENABLED=true
# Optional Studio and experimental defaults must not inherit provider credentials.
unset OPENAI_API_KEY S3_HOST S3_REGION S3_ACCESS_KEY S3_SECRET_KEY

[[ "$(timeout 30 "$cli" --version)" == "$version" ]] || fail "The local CLI must be exactly ${version}."
timeout 20 docker info --format '{{.ServerVersion}}' >/dev/null || fail 'Docker daemon is unavailable; start your configured container runtime.'

# Capture the real executable before adding the adapter only to the CLI child's
# PATH. Ordinary host Docker commands continue to use their original executable.
real_docker="$(command -v docker)"
[[ "$real_docker" == /* ]] || fail 'Docker must resolve to an absolute executable path.'
bash "$repo_root/scripts/install-loopback-adapter.sh"
adapter_revision="$(cd "$repo_root/docker/loopback-adapter" && sha256sum Dockerfile go.mod ./*.go | sha256sum | cut -d ' ' -f1)"
adapter_dir="$repo_root/.tools/loopback-adapter/$adapter_revision"
if "$windows"; then adapter_binary="$adapter_dir/docker.exe"; else adapter_binary="$adapter_dir/docker"; fi
adapter_environment=(env "AGRIFOS_REAL_DOCKER=$(native_path "$real_docker")"
    "AGRIFOS_ADAPTER_PROJECT=$project_id" "AGRIFOS_ADAPTER_NETWORK=$network"
    "AGRIFOS_ADAPTER_WORKDIR=$(native_path "$workdir")")
adapter_command=("${adapter_environment[@]}" "$adapter_binary")
cli_environment=("${adapter_environment[@]}" "PATH=$adapter_dir:$PATH")

sanitize_cli_output() {
    # Credential summaries emitted by the CLI must never enter terminal output or saved logs.
    sed -E \
        -e '/"(d|p|q|dp|dq|qi|k|password)"[[:space:]]*:/s/.*/[REDACTED_PRIVATE_MATERIAL]/' \
        -e '/"(ANON_KEY|SERVICE_ROLE_KEY|PUBLISHABLE_KEY|SECRET_KEY|JWT_SECRET|S3_PROTOCOL_ACCESS_KEY_ID|S3_PROTOCOL_ACCESS_KEY_SECRET)"[[:space:]]*:/s/.*/[REDACTED_CLI_CREDENTIAL_SUMMARY]/' \
        -e '/JWT_SECRET[[:space:]]*[=:]/s/.*/[REDACTED_JWT_SECRET]/' \
        -e 's/sb_(publishable|secret)_[A-Za-z0-9_-]+/[REDACTED_API_KEY]/g' \
        -e 's/eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/[REDACTED_JWT]/g' \
        -e 's#(postgres(ql)?(\+asyncpg)?://[^:/[:space:]]+:)[^@[:space:]]+@#\1[REDACTED]@#g'
}
project_containers() {
    timeout 20 docker ps -a --filter "label=com.supabase.cli.project=$project_id" --format '{{.Names}}'
}
assert_owned_resources() {
    local containers volumes networks all_containers all_volumes all_networks named_resources item actual_workdir
    containers="$(project_containers)" || fail 'Docker project container listing failed.'
    volumes="$(timeout 20 docker volume ls --filter "label=com.supabase.cli.project=$project_id" --format '{{.Name}}')" || fail 'Docker project volume listing failed.'
    networks="$(timeout 20 docker network ls --filter "label=com.supabase.cli.project=$project_id" --format '{{.Name}}')" || fail 'Docker project network listing failed.'
    all_containers="$(timeout 20 docker ps -a --format '{{.Names}}')" || fail 'Docker container listing failed.'
    all_volumes="$(timeout 20 docker volume ls --format '{{.Name}}')" || fail 'Docker volume listing failed.'
    all_networks="$(timeout 20 docker network ls --format '{{.Name}}')" || fail 'Docker network listing failed.'
    named_resources="$(printf '%s\n' "$all_containers" "$all_volumes" "$all_networks" |
        awk -v suffix="_$project_id" 'index($0, "supabase_") == 1 && substr($0, length($0)-length(suffix)+1) == suffix')" || fail 'Docker resource name verification failed.'
    if [[ -f "$owner_file" ]]; then
        [[ "$(cat -- "$owner_file")" == "$owner_description" ]] || fail 'The local ownership record differs; preserve existing resources before changing configuration.'
        while IFS= read -r item; do
            [[ -n "$item" ]] || continue
            actual_workdir="$(timeout 20 docker inspect --format '{{index .Config.Labels "com.supabase.cli.workdir"}}' "$item")" || fail 'Docker container ownership inspection failed.'
            [[ "$(normalized_path "$actual_workdir")" == "$(normalized_path "$(native_path "$workdir")")" ]] ||
                fail "Container $item belongs to another workdir; it will not be changed."
        done <<< "$containers"
    elif [[ -n "$containers$volumes$networks$named_resources" ]]; then
        fail "Preexisting Supabase resources for $project_id have no task ownership record; they will not be changed."
    fi
}
assert_network() {
    local found owner binding driver project
    found="$(timeout 20 docker network ls --format '{{.Name}}' | awk -v name="$network" '$0 == name {print}')" || fail 'Docker network listing failed.'
    [[ -n "$found" ]] || return 1
    owner="$(timeout 20 docker network inspect --format '{{index .Labels "com.agrifos.managed-by"}}' "$network")" || fail 'Docker network inspection failed.'
    project="$(timeout 20 docker network inspect --format '{{index .Labels "com.agrifos.project"}}' "$network")" || fail 'Docker network inspection failed.'
    binding="$(timeout 20 docker network inspect --format '{{index .Options "com.docker.network.bridge.host_binding_ipv4"}}' "$network")" || fail 'Docker network inspection failed.'
    driver="$(timeout 20 docker network inspect --format '{{.Driver}}' "$network")" || fail 'Docker network inspection failed.'
    [[ "$owner" == supabase-local.sh && "$project" == "$project_id" && "$binding" == 127.0.0.1 && "$driver" == bridge ]] ||
        fail "Existing network $network has incompatible ownership or binding; it will not be changed."
}
check_bindings() {
    local item binding containers bindings
    containers="$(project_containers)" || fail 'Docker project container listing failed.'
    while IFS= read -r item; do
        [[ -n "$item" ]] || continue
        bindings="$(timeout 20 docker inspect --format '{{range .NetworkSettings.Ports}}{{range .}}{{printf "%s:%s\n" .HostIp .HostPort}}{{end}}{{end}}' "$item")" || fail 'Docker published port inspection failed.'
        while IFS= read -r binding; do
            [[ -n "$binding" ]] || continue
            [[ "$binding" == 127.0.0.1:* ]] || fail "Container $item exposes binding $binding outside loopback; verification failed."
        done <<< "$bindings"
    done <<< "$containers"
}
show_status() {
    local item containers
    containers="$(project_containers)" || fail 'Docker project container listing failed.'
    printf 'Supabase CLI %s; project %s; network %s.\n' "$version" "$project_id" "$network"
    printf 'Auth/API: %s; PostgreSQL: 127.0.0.1:%s; mail: http://127.0.0.1:%s\n' "$api_url" "$db_port" "$mail_port"
    while IFS= read -r item; do
        [[ -n "$item" ]] || continue
        timeout 20 docker inspect --format '{{.Name}}: {{.State.Status}}{{if .State.Health}} ({{.State.Health.Status}}){{end}}' "$item"
    done <<< "$containers"
}
preflight_loopback_binding() (
    # Docker Desktop may ignore bridge default bindings. Verify the actual daemon
    # before Auth/DB/mail launch, using the already-built image with no listener.
    local probe_image='agrifos-backend:runtime' probe_ref='' probe_token probe_name
    local image_volumes existing identity running bindings binding result
    image_volumes="$(timeout 20 docker image inspect --format '{{len .Config.Volumes}}' "$probe_image" 2>/dev/null)" ||
        fail 'The loopback preflight requires agrifos-backend:runtime; run docker compose build migrate first.'
    [[ "$image_volumes" == 0 ]] || fail 'The preflight image must declare no volumes.'
    probe_token="$BASHPID-$RANDOM-$RANDOM"
    probe_name="agrifos-bind-probe-$project_id-$probe_token"
    existing="$(timeout 20 docker ps -a --filter "name=^$probe_name$" --format '{{.Names}}')" || fail 'Docker probe name verification failed.'
    [[ -z "$existing" ]] || fail 'A preflight probe name already exists; it will not be changed.'
    cleanup_probe() {
        result=$?
        trap - EXIT
        if [[ -n "$probe_ref" ]]; then
            identity="$(timeout 20 docker inspect --format '{{index .Config.Labels "com.agrifos.managed-by"}}|{{index .Config.Labels "com.agrifos.project"}}|{{index .Config.Labels "com.agrifos.probe-token"}}' "$probe_ref" 2>/dev/null)" || identity=''
            if [[ "$identity" == "supabase-local.sh|$project_id|$probe_token" ]]; then
                if ! timeout 20 docker rm --force "$probe_ref" >/dev/null; then
                    printf 'Preflight probe cleanup failed; inspect the labeled probe before retrying.\n' >&2
                    result=1
                fi
            else
                printf 'Preflight probe identity could not be verified; no existing resource was removed.\n' >&2
                result=1
            fi
        fi
        exit "$result"
    }
    trap cleanup_probe EXIT
    probe_ref="$probe_name"
    timeout 20 "${adapter_command[@]}" create --name "$probe_name" --restart no \
        --label com.agrifos.managed-by=supabase-local.sh --label "com.agrifos.project=$project_id" \
        --label "com.agrifos.probe-token=$probe_token" --network "$network" \
        --publish '0:8080' --entrypoint python "$probe_image" \
        -c 'import time; time.sleep(45)' >/dev/null || fail 'Docker preflight probe creation failed.'
    timeout 20 "${adapter_command[@]}" start "$probe_ref" >/dev/null || fail 'Docker preflight probe startup failed.'
    running="$(timeout 20 docker inspect --format '{{.State.Running}}' "$probe_ref")" || fail 'Docker preflight probe inspection failed.'
    [[ "$running" == true ]] || fail 'The bounded preflight probe exited before verification.'
    bindings="$(timeout 20 docker inspect --format '{{range .NetworkSettings.Ports}}{{range .}}{{printf "%s:%s\n" .HostIp .HostPort}}{{end}}{{end}}' "$probe_ref")" || fail 'Docker preflight port inspection failed.'
    [[ -n "$bindings" ]] || fail 'The preflight probe published no port; binding cannot be verified.'
    while IFS= read -r binding; do
        [[ "$binding" == 127.0.0.1:* ]] || fail "Docker publishes $binding outside loopback despite the bridge setting; refusing to launch Auth/DB/mail. No runtime configuration was changed."
    done <<< "$bindings"
    printf 'PASS: adapter and actual Docker published ports use explicit IPv4 loopback.\n'
)
cleanup_failed_start() {
    local result=$?
    trap - EXIT
    if [[ "$result" -ne 0 ]]; then
        if (assert_owned_resources) && (assert_network); then
            printf 'Startup verification failed; stopping only this owned project and preserving its volumes.\n' >&2
            if ! timeout --foreground 120 "${cli_environment[@]}" "$cli" --workdir "$(native_path "$workdir")" stop \
                --project-id "$project_id" 2>&1 | sanitize_cli_output; then
                printf 'Owned project stop failed; inspect its resource state before retrying.\n' >&2
            fi
        else
            printf 'Ownership or network verification failed; resources were preserved for inspection.\n' >&2
        fi
    fi
    exit "$result"
}

assert_owned_resources
case "$command_name" in
    check)
        if assert_network; then printf 'Owned bridge has a loopback default configured; preflight verifies the effective binding.\n'; fi
        printf 'PASS: pinned CLI, Docker daemon and local configuration.\n'
        ;;
    preflight)
        [[ -f "$owner_file" ]] || fail 'No task ownership record exists; start must create the owned bridge first.'
        assert_network || fail 'The owned network does not exist; start must create it first.'
        preflight_loopback_binding
        ;;
    status)
        assert_network || fail 'The local network does not exist; start Supabase first.'
        check_bindings
        show_status
        ;;
    start)
        mkdir -p -- "$state_dir"
        [[ "$(cd -- "$state_dir" && pwd -P)" == "$state_dir" ]] || fail 'Local state must resolve inside the selected workdir.'
        if ! assert_network; then
            timeout 20 docker network create --driver bridge \
                --label com.agrifos.managed-by=supabase-local.sh --label "com.agrifos.project=$project_id" \
                --opt com.docker.network.bridge.host_binding_ipv4=127.0.0.1 "$network" >/dev/null
        fi
        printf '%s\n' "$owner_description" > "$owner_file"
        preflight_loopback_binding
        if [[ ! -e "$key_file" ]]; then
            # gen signing-key reads the TOML path, not its environment override. Only
            # append to this newly created placeholder; never overwrite an existing key.
            (set -o noclobber; printf '[]\n' > "$key_file") || fail 'A signing key appeared concurrently; it was not overwritten.'
            if ! timeout 30 "${cli_environment[@]}" "$cli" --workdir "$(native_path "$workdir")" gen signing-key --algorithm ES256 --append \
                2>&1 | sanitize_cli_output > "$state_dir/key-generation.log"; then
                rm -f -- "$key_file"
                tail -n 15 -- "$state_dir/key-generation.log" >&2
                fail 'Local ES256 key generation failed; no existing key was overwritten.'
            fi
            chmod 600 -- "$key_file"
        fi
        excluded='realtime,storage-api,imgproxy,edge-runtime,logflare,vector,supavisor'
        if ! "$studio"; then excluded+=',postgrest,postgres-meta,studio'; fi
        start_timeout="${AGRIFOS_SUPABASE_START_TIMEOUT:-600}"
        [[ "$start_timeout" =~ ^[0-9]+$ && "$start_timeout" -ge 30 && "$start_timeout" -le 1800 ]] || fail 'Startup timeout must be between 30 and 1800 seconds.'
        printf 'Starting local Supabase; first use downloads pinned service images.\n'
        trap cleanup_failed_start EXIT
        if ! timeout --foreground "$start_timeout" "${cli_environment[@]}" "$cli" --workdir "$(native_path "$workdir")" start \
            --network-id "$network" --exclude "$excluded" 2>&1 | sanitize_cli_output > "$state_dir/start.log"; then
            tail -n 40 -- "$state_dir/start.log" >&2
            fail 'Supabase start failed; sanitized details are above. Local data were preserved.'
        fi
        assert_owned_resources
        assert_network || fail 'Supabase network is missing after startup.'
        check_bindings
        required_services=(db auth kong inbucket)
        if "$studio"; then required_services+=(rest pg_meta studio); fi
        for service in "${required_services[@]}"; do
            [[ "$(timeout 20 docker inspect --format '{{.State.Running}}' "supabase_${service}_$project_id")" == true ]] ||
                fail "Required Supabase service $service is not running; stop and restart the owned stack."
        done
        timeout 20 docker exec "supabase_db_$project_id" pg_isready --host 127.0.0.1 --port 5432 --username postgres --dbname postgres >/dev/null
        curl --fail --silent --show-error --connect-timeout 5 --max-time 15 "$api_url/auth/v1/health" >/dev/null
        curl --fail --silent --show-error --connect-timeout 5 --max-time 15 "$api_url/auth/v1/.well-known/jwks.json" >/dev/null
        show_status
        trap - EXIT
        ;;
    stop)
        [[ -f "$owner_file" ]] || fail 'No task ownership record exists; refusing to stop resources.'
        assert_network || fail 'The owned network is missing; refusing to stop resources.'
        timeout --foreground 120 "${cli_environment[@]}" "$cli" --workdir "$(native_path "$workdir")" stop --project-id "$project_id" \
            2>&1 | sanitize_cli_output
        printf 'Stopped owned local Supabase; database volumes and signing keys were preserved.\n'
        ;;
    destroy-test)
        [[ -f "$owner_file" ]] || fail 'No task ownership record exists; refusing destructive reset.'
        assert_network || fail 'The owned integration network is missing; refusing destructive reset.'
        printf 'Warning: permanently deleting Supabase data volumes for newly created integration project %s.\n' "$project_id" >&2
        timeout --foreground 120 "${cli_environment[@]}" "$cli" --workdir "$(native_path "$workdir")" stop \
            --project-id "$project_id" --no-backup 2>&1 | sanitize_cli_output
        printf 'Deleted integration Supabase data for %s; signing keys and shared network were retained.\n' "$project_id"
        ;;
esac
