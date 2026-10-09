"""Read local CLI status from stdin; never log keys or overwrite local env files."""
import argparse
import base64
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit, urlunsplit


def write_new(path, values):
    lines = []
    for key, value in values.items():
        if any(c in str(value) for c in "\r\n'\\"):
            raise ValueError(f"Unsupported characters for {key}")
        lines.append(f"{key}='{value}'\n")
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            os.chmod(path, 0o600)
            stream.writelines(lines)
        print(f"Created {path.name} (values omitted).")
    except FileExistsError:
        print(f"Preserved existing {path.name}.")


def main(output=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="agrifos")
    parser.add_argument("--port", type=int, default=54321)
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--integration", action="store_true")
    parser.add_argument("--api-service", choices=("api", "api-runtime"), default="api")
    args = parser.parse_args()
    if not args.project.startswith("agrifos") or not args.project.replace("-", "").isalnum():
        raise SystemExit("Unexpected local project identity.")
    status = json.load(sys.stdin)
    database = urlsplit(status["DB_URL"])
    if database.scheme not in ("postgresql", "postgres") or database.hostname not in ("127.0.0.1", "localhost") or database.query or database.fragment:
        raise SystemExit("Refusing non-local Supabase configuration.")
    public_url = f"http://127.0.0.1:{args.port}"
    internal_url = f"http://supabase_kong_{args.project}:8000"
    auth = database.netloc.rsplit("@", 1)[0]
    container_database = urlunsplit(("postgresql+asyncpg", f"{auth}@supabase_db_{args.project}:5432", database.path, database.query, ""))
    publishable = status.get("PUBLISHABLE_KEY") or status.get("ANON_KEY")
    if not publishable:
        raise SystemExit("Local CLI status did not contain a public client key.")
    if not publishable.startswith("sb_publishable_"):
        try:
            claims = json.loads(base64.urlsafe_b64decode(publishable.split(".")[1] + "=" * (-len(publishable.split(".")[1]) % 4)))
            if claims.get("role") != "anon":
                raise ValueError()
        except (ValueError, IndexError, TypeError):
            raise SystemExit("Refusing an administrative or malformed client key.") from None
    output = output or Path("/output")
    write_new(output / "backend.env", {"DATABASE_URL": container_database, "SUPABASE_URL": public_url, "SUPABASE_JWKS_URL": f"{internal_url}/auth/v1/.well-known/jwks.json", "ENV": "development", "APP_DEBUG": "false"})
    write_new(output / "client.env", {"SUPABASE_URL": f"http://10.0.2.2:{args.port}", "SUPABASE_PUBLISHABLE_KEY": publishable, "API_BASE_URL": f"http://10.0.2.2:{args.api_port}"})
    if args.integration:
        write_new(output / "integration.env", {"LOCAL_SUPABASE_URL": internal_url, "LOCAL_ANON_KEY": publishable, "LOCAL_SERVICE_ROLE_KEY": status["SERVICE_ROLE_KEY"], "API_BASE_URL": f"http://{args.api_service}:8000", "LOCAL_TEST_PROJECT": args.project})


if __name__ == "__main__":
    main()
