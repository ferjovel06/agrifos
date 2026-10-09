#!/usr/bin/env bash
set -Eeuo pipefail
umask 022

task="${1:-version}"
if (( $# > 0 )); then shift; fi
project=/workspace/app_flutter
child_pid=

fail() {
  printf 'Flutter container: %s\n' "$*" >&2
  exit 1
}

terminate() {
  if [[ -n "$child_pid" ]]; then
    kill -TERM "$child_pid" 2>/dev/null || :
    wait "$child_pid" 2>/dev/null || :
  fi
  exit 143
}
trap terminate TERM INT

run_command() {
  local status=0
  "$@" <&0 &
  child_pid=$!
  wait "$child_pid" || status=$?
  child_pid=
  return "$status"
}

seed_android_tools() {
  [[ -d /opt/android-tooling/22.0 ]] || fail 'Use the flutter-android service for Android tasks.'
  [[ -w "$ANDROID_SDK_ROOT" ]] || \
    fail 'This Linux SDK volume belongs to another UID; select a fresh Compose project namespace.'
  exec 8>"$ANDROID_SDK_ROOT/.agrifos-sdk.lock"
  flock --exclusive --timeout 30 8 || fail 'Another Android task is using this SDK.'
  mkdir -p "$ANDROID_SDK_ROOT/cmdline-tools/22.0"
  rsync -a /opt/android-tooling/22.0/ "$ANDROID_SDK_ROOT/cmdline-tools/22.0/"
}

require_reviewed_licenses() {
  [[ -s "$ANDROID_SDK_ROOT/licenses/android-sdk-license" ]] || \
    fail 'Run bash scripts/flutter-container.sh licenses interactively and review the SDK licenses first.'
}

verify_project() {
  local path
  for path in pubspec.yaml pubspec.lock .metadata android/settings.gradle.kts \
    android/build.gradle.kts android/app/build.gradle.kts android/gradle.properties \
    android/gradle/wrapper/gradle-wrapper.properties; do
    cmp -s "/source/$path" "$project/$path" || \
      fail "The tool changed $path in its isolated workspace. Investigate without updating the checkout automatically."
  done
}

prepare_project() {
  [[ -f /source/pubspec.yaml && -f /source/pubspec.lock ]] || \
    fail 'Mount app_flutter read-only at /source.'
  [[ -w /workspace && -w "$PUB_CACHE" && -w "$GRADLE_USER_HOME" ]] || \
    fail 'Linux cache/workspace volumes belong to another UID. Select a fresh Compose project namespace; do not change ownership of unrelated host files.'
  mkdir -p "$project"
  # This allowlist copies project inputs, while caches, generated wrappers and
  # build products stay exclusively in the Linux workspace. No host .env,
  # SDK paths, Windows cache, signing file or keystore enters the workspace.
  rsync -a --safe-links --delete \
    --exclude='.env*' --exclude='.git/' --exclude='.dart_tool/' \
    --exclude='.gradle/' --exclude='.cxx/' --exclude='build/' \
    --exclude='local.properties' --exclude='key.properties*' \
    --exclude='*.jks' --exclude='*.keystore' --exclude='*.pem' --exclude='*.key' \
    --include='/pubspec.yaml' --include='/pubspec.lock' \
    --include='/analysis_options.yaml' --include='/.metadata' \
    --include='/lib/***' --include='/test/***' --include='/assets/***' \
    --include='/android/' --include='/android/app/' \
    --include='/android/app/src/***' --include='/android/app/build.gradle.kts' \
    --include='/android/build.gradle.kts' --include='/android/settings.gradle.kts' \
    --include='/android/gradle.properties' --include='/android/gradle/' \
    --include='/android/gradle/wrapper/' \
    --include='/android/gradle/wrapper/gradle-wrapper.properties' \
    --exclude='*' /source/ "$project/"
  # Parse as data, never source the client's env file. Only these three public
  # settings may become the packaged asset; legacy JWT keys must have anon role.
  local client_file=/config/client.env
  if [[ ! -f "$client_file" ]]; then
    [[ "$task" != apk ]] || fail 'Mount a public client configuration at /config/client.env before building an APK.'
    client_file=/opt/agrifos/client.env.example
  fi
  python3 - "$client_file" "$project/.env" "$task" <<'PY'
import base64
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

allowed = {"SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "API_BASE_URL"}
values = {}
try:
    for raw in Path(sys.argv[1]).read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        name, value = name.strip(), value.strip()
        if not separator or name not in allowed or name in values:
            raise ValueError("The client env must contain only the three expected public settings, once each.")
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError("A quoted public setting is malformed.")
            value = value[1:-1]
        if not value or any(character in value for character in "\r\n\0"):
            raise ValueError("A public client setting is empty or malformed.")
        values[name] = value
    if values.keys() != allowed:
        raise ValueError("The client env is missing a required public setting.")
    for name in ("SUPABASE_URL", "API_BASE_URL"):
        url = urlsplit(values[name])
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            raise ValueError("Client URLs must be HTTP(S) URLs without embedded credentials.")
    key = values["SUPABASE_PUBLISHABLE_KEY"]
    if key == "your-publishable-key" and sys.argv[3] != "apk":
        pass
    elif re.fullmatch(r"sb_publishable_[A-Za-z0-9_-]+", key):
        pass
    else:
        pieces = key.split(".")
        if len(pieces) != 3:
            raise ValueError("Use a provider publishable key or a legacy anon JWT, never an administrative key.")
        claims = json.loads(base64.urlsafe_b64decode(pieces[1] + "=" * (-len(pieces[1]) % 4)))
        if not isinstance(claims, dict) or claims.get("role") != "anon":
            raise ValueError("Only the anon role is allowed in a legacy client JWT.")
    Path(sys.argv[2]).write_text("".join(f"{name}={values[name]}\n" for name in sorted(allowed)), encoding="utf-8")
except (ValueError, TypeError, json.JSONDecodeError) as error:
    print(f"Flutter container: {error}", file=sys.stderr)
    sys.exit(1)
PY
  cd "$project"
  trap 'status=$?; verify_project; exit "$status"' EXIT
  run_command flutter pub get --enforce-lockfile
  verify_project
}

case "$task" in
  version)
    (( $# == 0 )) || fail 'version takes no extra arguments.'
    flutter --version
    dart --version
    java -version
    if [[ -d /opt/android-tooling/22.0 ]]; then
      seed_android_tools
      sdkmanager --sdk_root="$ANDROID_SDK_ROOT" --version
    fi
    exit 0
    ;;
  licenses)
    (( $# == 0 )) || fail 'licenses takes no extra arguments.'
    [[ -t 0 && -t 1 ]] || fail 'License review requires an interactive terminal; run this task yourself.'
    seed_android_tools
    run_command sdkmanager --sdk_root="$ANDROID_SDK_ROOT" --licenses
    require_reviewed_licenses
    exit 0
    ;;
  sdk)
    (( $# == 0 )) || fail 'sdk takes no extra arguments.'
    seed_android_tools
    require_reviewed_licenses
    # Closing stdin refuses any new license prompt instead of accepting it.
    run_command sdkmanager --sdk_root="$ANDROID_SDK_ROOT" \
      'platforms;android-36' 'build-tools;36.0.0' 'ndk;28.2.13676358' </dev/null
    if [[ -d "$ANDROID_SDK_ROOT/platform-tools" ]]; then
      grep -Eq '^Pkg.Revision[[:space:]]*=[[:space:]]*37\.0\.1[[:space:]]*$' \
        "$ANDROID_SDK_ROOT/platform-tools/source.properties" || \
        fail 'This SDK volume has different Platform Tools; use a separate Agrifos SDK volume instead of overwriting them.'
    else
      unzip -q /opt/android-tooling/platform-tools.zip -d "$ANDROID_SDK_ROOT"
    fi
    printf 'Installed SDK platform 36, Build Tools 36.0.0, NDK 28.2.13676358 and Platform Tools 37.0.1.\n'
    exit 0
    ;;
  restore|analyze|test|apk) ;;
  *) fail 'Supported tasks: version, restore, analyze, test, licenses, sdk, apk.' ;;
esac

# Serialize access to a shared Linux workspace without changing host ownership.
[[ -w /workspace ]] || \
  fail 'This Linux workspace belongs to another UID; select a fresh Compose project namespace.'
exec 9>/workspace/.agrifos-flutter.lock
flock --exclusive --timeout 30 9 || fail 'Another Flutter task is using this workspace.'
prepare_project

case "$task" in
  restore)
    (( $# == 0 )) || fail 'restore takes no extra arguments.'
    ;;
  analyze) run_command flutter analyze --no-pub "$@" ;;
  test) run_command flutter test --no-pub "$@" ;;
  apk)
    (( $# == 0 )) || fail 'apk builds debug only and takes no extra arguments.'
    [[ -w /artifacts ]] || fail 'The artifacts mount is not writable by the selected host UID/GID.'
    seed_android_tools
    require_reviewed_licenses
    [[ -d "$ANDROID_SDK_ROOT/platforms/android-36" \
      && -d "$ANDROID_SDK_ROOT/build-tools/36.0.0" \
      && -d "$ANDROID_SDK_ROOT/ndk/28.2.13676358" \
      && -x "$ANDROID_SDK_ROOT/platform-tools/adb" ]] || \
      fail 'Provision the pinned SDK first with bash scripts/flutter-container.sh sdk.'
    run_command flutter build apk --debug --no-pub
    verify_project
    install -m 0644 build/app/outputs/flutter-apk/app-debug.apk /artifacts/agrifos-debug.apk
    printf 'APK debug exported to the mounted artifacts directory: agrifos-debug.apk\n'
    ;;
esac
