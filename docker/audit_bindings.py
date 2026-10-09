"""Verify only credential-free port-inspection records saved by the driver."""
import json
from pathlib import Path
import re
import sys

def audit(records, project, api_service="api"):
    if not re.fullmatch(r"agrifos-it-[0-9a-f]{8}", project):
        raise ValueError("invalid integration project")
    if api_service not in ("api", "api-runtime"):
        raise ValueError("invalid API service")
    expected = {f"/supabase_{service}_{project}" for service in ("db", "auth", "kong", "inbucket")}
    expected.add(f"/{project}-{api_service}-1")
    if {record["name"] for record in records} != expected or len(records) != len(expected):
        raise ValueError("incomplete or foreign container inventory")
    count = 0
    for record in records:
        for field in ("requested", "actual"):
            for entries in (record[field] or {}).values():
                for entry in entries or []:
                    if entry["HostIp"] != "127.0.0.1":
                        raise ValueError("non-loopback binding")
                    if field == "actual":
                        if not 0 < int(entry["HostPort"]) <= 65535:
                            raise ValueError("invalid resolved host port")
                        count += 1
        for port, entries in (record["requested"] or {}).items():
            if entries and not (record["actual"] or {}).get(port):
                raise ValueError("requested port has no resolved binding")
    if count != 4:
        raise ValueError("expected API, gateway, database and mail published ports")
    return count


if __name__ == "__main__":
    try:
        records = [json.loads(line) for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()]
        count = audit(records, sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "api")
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        raise SystemExit("FAIL: incomplete inventory or unsafe published port evidence") from None
    print(f"PASS: {len(records)} containers inspected; {count} published ports restricted to 127.0.0.1.")
