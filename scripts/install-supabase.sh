#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
version='2.120.0'
release_url="https://github.com/supabase/cli/releases/download/v${version}"
install_dir="$repo_root/.tools/supabase"

fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }
for tool in curl sha256sum mktemp timeout; do
    command -v "$tool" >/dev/null 2>&1 || fail "$tool is required."
done

case "$(uname -s):$(uname -m)" in
    Linux:x86_64)
        archive="supabase_${version}_linux_amd64.tar.gz"
        archive_sha256='7074584113aa00495beeac661c41fb09f1ddd0a483cd7333894b0d080086dc6e'
        binaries=(supabase supabase-go)
        command -v tar >/dev/null 2>&1 || fail 'tar is required.'
        ;;
    MINGW*:x86_64|MSYS*:x86_64)
        archive="supabase_${version}_windows_amd64.zip"
        archive_sha256='0db5224fc5d92ae5f15e675ed65dad376967326921122ab8d9a78e790874c92e'
        binaries=(supabase.exe supabase-go.exe)
        command -v unzip >/dev/null 2>&1 || fail 'unzip is required in Git Bash.'
        ;;
    *) fail 'Supported hosts: Linux x86_64 or Windows x64 with Git Bash.' ;;
esac

if [[ -e "$install_dir/${binaries[0]}" || -e "$install_dir/${binaries[1]}" ]]; then
    [[ -f "$install_dir/${binaries[0]}" && -f "$install_dir/${binaries[1]}" ]] ||
        fail 'An incomplete local Supabase installation exists; preserve or remove it manually.'
    installed_version="$(SUPABASE_TELEMETRY_DISABLED=1 timeout 30 "$install_dir/${binaries[0]}" --version)"
    [[ "$installed_version" == "$version" ]] || fail "Existing local CLI version is not ${version}; it will not be overwritten."
    printf 'Supabase CLI %s is already installed locally.\n' "$version"
    exit 0
fi

mkdir -p -- "$repo_root/.tools"
[[ "$(cd -- "$repo_root/.tools" && pwd -P)" == "$repo_root/.tools" ]] || fail 'The .tools directory must remain inside this repository.'
mkdir -p -- "$install_dir"
[[ "$(cd -- "$install_dir" && pwd -P)" == "$install_dir" ]] || fail 'The installation directory must remain inside this repository.'
staging_dir="$(mktemp -d "$repo_root/.tools/.supabase-install.XXXXXX")"
[[ "$staging_dir" == "$repo_root/.tools/.supabase-install."* ]] || fail 'Unsafe staging directory.'
cleanup() {
    # Only these task-created files are removed, never an existing installation.
    rm -f -- "$staging_dir/$archive" "$staging_dir/checksums.txt" "$staging_dir/expected.sha256" \
        "$staging_dir/supabase" "$staging_dir/supabase-go" \
        "$staging_dir/supabase.exe" "$staging_dir/supabase-go.exe"
    rmdir -- "$staging_dir"
}
trap cleanup EXIT

printf 'Downloading the pinned Supabase CLI %s for this host.\n' "$version"
curl --fail --location --silent --show-error --proto '=https' --tlsv1.2 \
    --connect-timeout 20 --max-time 120 --retry 2 \
    "$release_url/checksums.txt" --output "$staging_dir/checksums.txt"
published_sha256="$(awk -v asset="$archive" '$2 == asset { print $1 }' "$staging_dir/checksums.txt")"
[[ "$published_sha256" == "$archive_sha256" ]] || fail 'Official release checksum differs from the reviewed pin; investigate before updating it.'
printf '%s  %s\n' "$archive_sha256" "$archive" > "$staging_dir/expected.sha256"
curl --fail --location --silent --show-error --proto '=https' --tlsv1.2 \
    --connect-timeout 20 --max-time 600 --retry 2 \
    "$release_url/$archive" --output "$staging_dir/$archive"
(
    cd -- "$staging_dir"
    sha256sum --check --status expected.sha256
) || fail 'Supabase archive checksum does not match the official release.'

if [[ "$archive" == *.zip ]]; then
    unzip -q "$staging_dir/$archive" "${binaries[@]}" -d "$staging_dir"
else
    tar -xzf "$staging_dir/$archive" -C "$staging_dir" -- "${binaries[@]}"
fi
chmod u+x -- "$staging_dir/${binaries[0]}" "$staging_dir/${binaries[1]}"
[[ "$(SUPABASE_TELEMETRY_DISABLED=1 timeout 30 "$staging_dir/${binaries[0]}" --version)" == "$version" ]] ||
    fail 'The downloaded CLI did not report the pinned version.'
mv -- "$staging_dir/${binaries[0]}" "$staging_dir/${binaries[1]}" "$install_dir/"
printf 'Installed verified Supabase CLI %s in .tools/supabase/ (both executables).\n' "$version"
