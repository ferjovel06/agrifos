#!/usr/bin/env bash
# Read-only local monitoring. Never include credentials in HEALTH_BASE_URL.
set -u
base_url="${HEALTH_BASE_URL:-http://127.0.0.1:8000}"
status=0
for endpoint in health health/db; do
  if curl --fail --silent --show-error --max-time 10 --output /dev/null "${base_url%/}/$endpoint"; then
    printf '%s OK %s\n' "$(date -u +%FT%TZ)" "$endpoint"
  else
    printf '%s FAIL %s\n' "$(date -u +%FT%TZ)" "$endpoint" >&2
    status=1
  fi
done
df -h / || status=1
free -m || status=1
exit "$status"
