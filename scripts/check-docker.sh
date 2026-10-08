#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
mode="${1:-static}"
if (( $# > 1 )); then
  printf 'Usage: bash scripts/check-docker.sh {static|config|lint|images}\n' >&2
  exit 2
fi
cd "$repo_root"
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'

# Deliberate upgrades: verify these versions/checksums against the official
# release assets and re-resolve the Trivy digest before changing the pins.
# https://github.com/hadolint/hadolint/releases/tag/v2.15.1
# https://github.com/aquasecurity/trivy/releases/tag/v0.75.0
hadolint_version=2.15.1
trivy_image='aquasec/trivy:0.75.0@sha256:af6acf9a6b85dfe389a1941505c0ce9efef52a4719635e1a962f022a3d855daa'
# Verification needs only Python's stdlib. Do not execute the scanned local ID:
# a concurrent build may untag/remove its OCI index after the archive is saved.
identity_image='python:3.13.16-slim-trixie@sha256:bf44cdfcb76cd3b41e879bc058fc37ec5872002ccfde7fcb765e218cde0cd79c'

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
native_path() {
  case "$(uname -s)" in MINGW*|MSYS*) cygpath -w "$1" ;; *) printf '%s\n' "$1" ;; esac
}
compose() {
  docker compose --project-directory "$(native_path "$repo_root")" \
    --file "$(native_path "$repo_root/compose.yaml")" "$@"
}

check_config() {
  command -v docker >/dev/null 2>&1 || fail 'Docker CLI with Compose v2 is required.'
  # Never print the expanded Compose configuration or resolved environment.
  compose config --quiet
  printf 'PASS: Compose configuration (quiet; daemon not required).\n'
  local count=0 script
  while IFS= read -r -d '' script; do
    bash -n "$script"
    printf 'PASS: Bash syntax %s\n' "${script#"$repo_root/"}"
    count=$((count + 1))
  done < <(find "$repo_root/scripts" "$repo_root/docker" -type f -name '*.sh' -print0)
  (( count > 0 )) || fail 'No Bash scripts were found; zero checks is not success.'
}

install_hadolint() {
  local asset expected_sha binary_name installed_version
  case "$(uname -s):$(uname -m)" in
    Linux:x86_64)
      asset=hadolint-linux-x86_64
      binary_name=hadolint
      expected_sha=c7187db94eeeeca956519a6af171adc31453941a1e777961f6e680f697c8c507
      ;;
    MINGW*:x86_64|MSYS*:x86_64)
      asset=hadolint-windows-x86_64.exe
      binary_name=hadolint.exe
      expected_sha=01d927294962b5387f9ead4f18679158452be4f17c765ad0bdffe5264b9c7b0a
      ;;
    *) fail 'Hadolint bootstrap supports Linux x86_64 and Windows x64/Git Bash.' ;;
  esac
  for tool in curl sha256sum mktemp timeout; do
    command -v "$tool" >/dev/null 2>&1 || fail "$tool is required for local Hadolint verification."
  done
  local install_dir="$repo_root/.tools/hadolint"
  hadolint_binary="$install_dir/$binary_name"
  mkdir -p "$install_dir"
  [[ "$(cd "$install_dir" && pwd -P)" == "$install_dir" ]] || fail 'Hadolint directory must stay inside this checkout.'
  if [[ -e "$hadolint_binary" ]]; then
    [[ -f "$hadolint_binary" ]] || fail 'Existing Hadolint path is not a regular file; it will not be replaced.'
    [[ "$(sha256sum "$hadolint_binary" | cut -d ' ' -f1)" == "$expected_sha" ]] || \
      fail 'Existing Hadolint does not match the pinned checksum; preserve it and resolve the mismatch explicitly.'
  else
    local staging_dir official_sha release_url
    staging_dir="$(mktemp -d "$repo_root/.tools/.hadolint-install.XXXXXX")"
    [[ "$staging_dir" == "$repo_root/.tools/.hadolint-install."* ]] || fail 'Unsafe Hadolint staging path.'
    release_url="https://github.com/hadolint/hadolint/releases/download/v${hadolint_version}"
    curl --fail --location --silent --show-error --proto '=https' --tlsv1.2 \
      --connect-timeout 20 --max-time 120 --retry 2 \
      "$release_url/checksums.sha256" --output "$staging_dir/checksums.sha256"
    official_sha="$(awk -v asset="$asset" '{name=$2; sub(/^\*/, "", name); sub(/\r$/, "", name); if (name == asset) print $1}' "$staging_dir/checksums.sha256")"
    [[ "$official_sha" == "$expected_sha" ]] || fail 'Official Hadolint release checksum differs from the reviewed pin.'
    curl --fail --location --silent --show-error --proto '=https' --tlsv1.2 \
      --connect-timeout 20 --max-time 180 --retry 2 \
      "$release_url/$asset" --output "$staging_dir/$asset"
    [[ "$(sha256sum "$staging_dir/$asset" | cut -d ' ' -f1)" == "$expected_sha" ]] || fail 'Hadolint download checksum mismatch.'
    chmod 0755 "$staging_dir/$asset"
    # A concurrent local bootstrap must not cause an existing binary to be replaced.
    [[ ! -e "$hadolint_binary" ]] || fail 'Hadolint appeared while downloading; rerun to verify it without replacing it.'
    mv "$staging_dir/$asset" "$hadolint_binary"
    rm -f "$staging_dir/checksums.sha256"
    rmdir "$staging_dir"
  fi
  installed_version="$(timeout 30 "$hadolint_binary" --version)"
  [[ "$installed_version" =~ (^|[[:space:]])2\.15\.1([[:space:]]|$) ]] || fail 'Hadolint did not report version 2.15.1.'
  printf '%s\n' "$installed_version"
}

check_lint() {
  install_hadolint
  # Prevent personal environment overrides from disabling the committed policy.
  local variable dockerfile
  for variable in ${!HADOLINT_@}; do unset "$variable"; done
  for dockerfile in backend/Dockerfile docker/flutter/Dockerfile docker/loopback-adapter/Dockerfile; do
    "$hadolint_binary" --config "$(native_path "$repo_root/.hadolint.yaml")" \
      --failure-threshold error --disable-ignore-pragma --no-color \
      "$(native_path "$repo_root/$dockerfile")"
    printf 'PASS: Hadolint errors %s; any printed warnings remain review findings.\n' "$dockerfile"
  done
}

check_images() {
  command -v docker >/dev/null 2>&1 || fail 'Docker CLI and a running Linux daemon are required.'
  local runtime_image="${AGRIFOS_SCAN_IMAGE:-agrifos-backend:runtime}" runtime_id runtime_platform
  case "$runtime_image" in agrifos-backend:runtime|agrifos-backend-evaluation:trixie-runtime) ;; *) fail 'Only the Agrifos runtime and isolated Trixie evaluation image can be scanned.' ;; esac
  if ! runtime_id="$(docker image inspect --format '{{.Id}}' "$runtime_image")"; then
    printf 'NOT RUN: build the backend runtime first: docker compose build migrate.\n' >&2
    exit 3
  fi
  runtime_platform="$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$runtime_image")"
  [[ "$runtime_platform" == linux/amd64 ]] || fail 'Image scanning currently supports a Linux amd64 backend runtime.'
  local evidence_dir="$repo_root/.docker/evidence/scanners"
  if [[ "$runtime_image" == agrifos-backend-evaluation:trixie-runtime ]]; then evidence_dir+="-trixie"; fi
  local cache_dir="$repo_root/.tools/trivy-cache"
  mkdir -p "$evidence_dir" "$cache_dir"
  [[ "$(cd "$evidence_dir" && pwd -P)" == "$evidence_dir" ]] || fail 'Scanner evidence must stay inside this checkout.'
  [[ "$(cd "$cache_dir" && pwd -P)" == "$cache_dir" ]] || fail 'Scanner cache must stay inside this checkout.'
  # Retain prior evidence, but never let a scanner failure reuse an old report.
  local previous_dir report_name
  mkdir -p "$evidence_dir/history"
  previous_dir="$(mktemp -d "$evidence_dir/history/scan.XXXXXXXX")"
  for report_name in runtime-image-id.txt runtime-identity.json trivy-config.json trivy-runtime.json; do
    [[ ! -L "$evidence_dir/$report_name" ]] || fail 'Scanner evidence must not be a symlink.'
    if [[ -f "$evidence_dir/$report_name" ]]; then mv "$evidence_dir/$report_name" "$previous_dir/$report_name"; fi
  done
  printf '%s\n' "$runtime_id" > "$evidence_dir/runtime-image-id.txt"
  # Export the inspected immutable ID even if a concurrent build replaces the tag.
  docker image save --output "$(native_path "$evidence_dir/runtime-image.tar")" "$runtime_id"
  local scanner_uid=1000 scanner_gid=1000
  case "$(uname -s)" in MINGW*|MSYS*) ;; *) scanner_uid="$(id -u)"; scanner_gid="$(id -g)" ;; esac
  local scanner_options=(--rm --platform linux/amd64 --user "$scanner_uid:$scanner_gid"
    --read-only --cap-drop ALL --security-opt no-new-privileges:true
    --tmpfs /tmp:rw,noexec,nosuid,size=256m --env HOME=/tmp
    --mount "type=bind,source=$(native_path "$cache_dir"),target=/cache"
    --mount "type=bind,source=$(native_path "$evidence_dir"),target=/output")
  docker run "${scanner_options[@]}" "$trivy_image" version
  local config_status=0 image_status=0 identity_status=0
  # The scanner sees only the reviewed Dockerfiles/Compose file, never .env or
  # a Docker socket. Security findings and scanner failures both block this mode.
  docker run "${scanner_options[@]}" \
    --mount "type=bind,source=$(native_path "$repo_root/backend/Dockerfile"),target=/input/backend/Dockerfile,readonly" \
    --mount "type=bind,source=$(native_path "$repo_root/docker/flutter/Dockerfile"),target=/input/flutter/Dockerfile,readonly" \
    --mount "type=bind,source=$(native_path "$repo_root/docker/loopback-adapter/Dockerfile"),target=/input/adapter/Dockerfile,readonly" \
    --mount "type=bind,source=$(native_path "$repo_root/compose.yaml"),target=/input/compose.yaml,readonly" \
    "$trivy_image" config --cache-dir /cache --timeout 10m --severity HIGH,CRITICAL \
      --exit-code 1 --format json --output /output/trivy-config.json /input || config_status=$?
  docker run "${scanner_options[@]}" \
    --mount "type=bind,source=$(native_path "$evidence_dir/runtime-image.tar"),target=/input/runtime-image.tar,readonly" \
    "$trivy_image" image --cache-dir /cache --timeout 10m --input /input/runtime-image.tar \
      --scanners vuln,secret --image-config-scanners misconfig,secret --severity HIGH,CRITICAL \
      --exit-code 1 --format json --output /output/trivy-runtime.json || image_status=$?
  if [[ -s "$evidence_dir/trivy-runtime.json" ]]; then
    docker run --rm --network none --user "$scanner_uid:$scanner_gid" --read-only \
      --cap-drop ALL --security-opt no-new-privileges:true \
      --mount "type=bind,source=$(native_path "$evidence_dir"),target=/evidence" \
      --mount "type=bind,source=$(native_path "$repo_root/docker/verify_scan_identity.py"),target=/verify.py,readonly" \
      "$identity_image" python /verify.py /evidence/runtime-image.tar /evidence/trivy-runtime.json \
        /evidence/runtime-identity.json "$runtime_id" || identity_status=$?
  else
    printf 'NOT RUN: runtime identity check; this scan produced no report.\n' >&2
    identity_status=1
  fi
  # Remove only this task's exported archive; retain reports and the inspected ID.
  rm -f "$evidence_dir/runtime-image.tar"
  if (( config_status != 0 || image_status != 0 || identity_status != 0 )); then
    fail "Trivy configuration/image check failed or found HIGH/CRITICAL issues (config=$config_status, image=$image_status, identity=$identity_status). Review .docker/evidence/scanners reports and logs."
  fi
  [[ -s "$evidence_dir/trivy-config.json" && -s "$evidence_dir/trivy-runtime.json" ]] || fail 'Trivy did not produce both reports.'
  printf 'PASS: Trivy 0.75.0 scanned actual backend runtime %s and configuration; no HIGH/CRITICAL findings.\n' "$runtime_id"
}

case "$mode" in
  static) check_config; check_lint ;;
  config) check_config ;;
  lint) check_lint ;;
  images) check_images ;;
  *) fail 'Supported modes: static, config, lint, images.' ;;
esac
