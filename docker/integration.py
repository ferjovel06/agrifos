"""Real Auth integration, restricted to a newly created Agrifos test project."""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import struct
import sys
import time
import uuid
from urllib.parse import urlsplit

import httpx
import jwt
import psycopg2


def validate_local_targets(environment):
    project = environment.get("LOCAL_TEST_PROJECT", "")
    if not re.fullmatch(r"agrifos-it-[a-f0-9]{8}", project):
        raise SystemExit("Refusing integration outside a dedicated agrifos-it-* project.")
    base = environment.get("LOCAL_SUPABASE_URL", "")
    api = environment.get("API_BASE_URL", "")
    if base != f"http://supabase_kong_{project}:8000" or api != "http://api:8000":
        raise SystemExit("Refusing Auth/API destinations outside this isolated Docker project.")
    database = urlsplit(environment.get("DATABASE_URL", ""))
    if database.scheme != "postgresql+asyncpg" or database.hostname != f"supabase_db_{project}" or database.port != 5432 or database.path != "/postgres" or database.query or database.fragment:
        raise SystemExit("Refusing a database outside this isolated Docker project.")
    return project, base, api


PROJECT, BASE, API = validate_local_targets(os.environ)
STATE = Path("/evidence/auth-state.json")
HEAD = "b2c4d6e8f901"


def request(method, path, *, admin=False, token=None, payload=None, expected=200):
    key = os.environ["LOCAL_SERVICE_ROLE_KEY"] if admin else os.environ["LOCAL_ANON_KEY"]
    headers = {"apikey": key}
    if admin or token:
        headers["Authorization"] = f"Bearer {key if admin else token}"
    response = httpx.request(method, BASE + "/auth/v1" + path, headers=headers, json=payload, timeout=15)
    if response.status_code != expected:
        # Response bodies can include tokens: report status and route only.
        raise AssertionError(f"Auth {method} {path}: expected {expected}, got {response.status_code}")
    return response.json() if response.content else {}


def login(state):
    return request("POST", "/token?grant_type=password", payload={"email": state["email"], "password": state["password"]})["access_token"]


def api_check(token, expected):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = httpx.get(API + "/users/me", headers=headers, timeout=15)
    if response.status_code != expected:
        raise AssertionError(f"/users/me expected {expected}, got {response.status_code}")
    return response.json() if expected == 200 else None


def database_check(user_id):
    with psycopg2.connect(os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://"), connect_timeout=5) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT version_num FROM alembic_version")
            assert cursor.fetchone() == (HEAD,), "Unexpected Alembic head"
            cursor.execute("SELECT id FROM public.users WHERE id = %s", (user_id,))
            assert str(cursor.fetchone()[0]) == user_id, "Auth profile trigger did not persist a profile"


def reject_invalid_claims(token):
    # Only the freshly generated key for this isolated test project is mounted.
    # Use a valid local signature so claim failures cannot be masked by bad crypto.
    header = jwt.get_unverified_header(token)
    keys = json.loads(Path("/test-signing-keys.json").read_text(encoding="utf-8"))
    if isinstance(keys, dict):
        keys = keys.get("keys", [keys])
    matching = [key for key in keys if key.get("kid") == header["kid"]]
    assert len(matching) == 1, "Missing isolated test signing key"
    jwk = matching[0]
    assert jwk.get("kty") == "EC" and jwk.get("alg") == "ES256" and "d" in jwk
    signing_key = jwt.PyJWK.from_dict(jwk).key
    claims = jwt.decode(token, options={"verify_signature": False})
    for change in (
        {"aud": "unauthorized-audience"},
        {"iss": "https://unauthorized.example/auth/v1"},
        {"exp": int(time.time()) - 60},
    ):
        invalid = jwt.encode({**claims, **change}, signing_key, algorithm="ES256", headers={"kid": header["kid"]})
        api_check(invalid, 401)
    api_check(jwt.encode(claims, "isolated-test-only-hmac-key-32-bytes", algorithm="HS256", headers={"kid": header["kid"]}), 401)
    api_check("malformed-token", 401)
    print("PASS: real API rejects signed ES256 tokens with wrong audience/issuer/expiry, HS256 and malformed tokens.")


def totp(secret):
    key = base64.b32decode(secret.upper() + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", int(time.time()) // 30), hashlib.sha1).digest()
    offset = digest[-1] & 15
    return f"{(struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7fffffff) % 1000000:06d}"


def initial():
    assert not STATE.exists(), "Test state exists; choose a new isolated test project"
    state = {"email": f"docker-{uuid.uuid4().hex}@example.invalid", "password": secrets.token_urlsafe(30), "project": PROJECT}
    user = request("POST", "/admin/users", admin=True, payload={"email": state["email"], "password": state["password"], "email_confirm": True, "user_metadata": {"name": "Docker integration"}})
    state["id"] = user["id"]
    STATE.parent.mkdir(exist_ok=True)
    with STATE.open("x", encoding="utf-8") as stream:
        os.chmod(STATE, 0o600)
        json.dump(state, stream)
    # Check BEFORE /users/me, whose repository can repair a missing profile.
    database_check(state["id"])
    token = login(state)
    assert jwt.get_unverified_header(token)["alg"] == "ES256", "Auth did not issue ES256"
    assert api_check(token, 200)["id"] == state["id"]
    reject_invalid_claims(token)
    api_check(None, 401)
    parts = token.split(".")
    altered = bytearray(base64.urlsafe_b64decode(parts[2] + "=" * (-len(parts[2]) % 4)))
    altered[0] ^= 1
    api_check(".".join(parts[:2] + [base64.urlsafe_b64encode(altered).decode().rstrip("=")]), 401)
    request("POST", "/token?grant_type=password", payload={"email": state["email"], "password": "incorrect-password"}, expected=400)
    database_check(state["id"])
    print("PASS: real ES256 login, profile trigger, protected API, invalid token/password, migration head.")
    enrolled = request("POST", "/factors", token=token, payload={"factor_type": "totp", "friendly_name": "Docker integration"})
    challenge = request("POST", f"/factors/{enrolled['id']}/challenge", token=token, payload={})
    verified = request("POST", f"/factors/{enrolled['id']}/verify", token=token, payload={"challenge_id": challenge["id"], "code": totp(enrolled["totp"]["secret"])})
    api_check(token, 403)
    api_check(verified["access_token"], 200)
    request("DELETE", f"/factors/{enrolled['id']}", token=verified["access_token"])
    print("PASS: real TOTP enrollment/verification, AAL1 rejected and AAL2 accepted.")


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else "initial"
    for endpoint in ("/health", "/health/db"):
        assert httpx.get(API + endpoint, timeout=10).status_code == 200, endpoint
    print("PASS: real /health and /health/db return 200.")
    if phase == "initial":
        initial()
    else:
        state = json.loads(STATE.read_text(encoding="utf-8"))
        assert state["project"] == PROJECT, "Test state belongs to a different project"
        if phase == "persistence":
            assert api_check(login(state), 200)["id"] == state["id"]
            database_check(state["id"])
            print("PASS: user and application profile survived restart and repeated migration.")
        elif phase == "cleanup":
            request("DELETE", f"/admin/users/{state['id']}", admin=True)
            STATE.unlink()
            print("Removed only the synthetic user from this new test project.")
        else:
            raise SystemExit("Unknown integration phase")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Avoid httpx/DB exception strings that may contain credentials.
        detail = str(error) if isinstance(error, AssertionError) else type(error).__name__
        print(f"FAIL: integration {detail}.", file=sys.stderr)
        raise SystemExit(1) from None
