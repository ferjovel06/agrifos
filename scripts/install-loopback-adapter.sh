#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
native_path() {
    case "$(uname -s)" in MINGW*|MSYS*) cygpath -w "$1" ;; *) printf '%s\n' "$1" ;; esac
}
case "$(uname -s):$(uname -m)" in
    Linux:x86_64) binary=docker ;;
    MINGW*:x86_64|MSYS*:x86_64) binary=docker.exe ;;
    *) fail 'Adapter supports Linux x86_64 and Windows x64/Git Bash.' ;;
esac
source_dir="$repo_root/docker/loopback-adapter"
revision="$(cd "$source_dir" && sha256sum Dockerfile go.mod ./*.go | sha256sum | cut -d ' ' -f1)"
output="$repo_root/.tools/loopback-adapter/$revision"
mkdir -p "$output"
[[ "$(cd "$output" && pwd -P)" == "$output" ]] || fail 'Adapter output must stay inside this checkout.'
if [[ ! -f "$output/verified.sha256" ]]; then
    docker build --progress plain --build-arg "SOURCE_REVISION=$revision" \
        --output "type=local,dest=$(native_path "$output")" "$(native_path "$source_dir")"
    if [[ "$binary" == docker.exe ]]; then "$output/adapter.test.exe" -test.v; fi
    (cd "$output" && sha256sum docker docker.exe adapter.test.exe > verified.sha256)
fi
(cd "$output" && sha256sum --check --status verified.sha256) || fail 'Adapter binary checksum changed; preserve and investigate the local artifact.'
[[ "$("$output/$binary" --agrifos-adapter-version)" == "$revision" ]] || fail 'Adapter revision does not match its source.'
printf 'PASS: local loopback adapter %s (%s).\n' "$revision" "$binary"
