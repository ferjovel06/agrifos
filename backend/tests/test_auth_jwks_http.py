"""Exercise the real JWKS HTTP transport and ES256 verifier on loopback."""

import json
import threading
import time
import unittest
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.core import auth


class JwksHttpTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(self.key.public_key()))
        self.jwk.update(kid="trusted-key", alg="ES256", use="sig")
        self.state = {"status": 200, "keys": [self.jwk], "requests": 0}
        self.destination = {"status": 200, "keys": [self.jwk], "requests": 0}
        self.target_url = self.server(self.destination)
        self.state["location"] = self.target_url
        self.url = self.server(self.state)
        self.client = jwt.PyJWKClient(self.url, cache_keys=True, lifespan=3600, timeout=5)

    def server(self, state):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                state["requests"] += 1
                self.send_response(state["status"])
                if "location" in state:
                    self.send_header("Location", state["location"])
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"keys": state["keys"]}).encode())

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_port}/jwks.json"

    def token(self, *, key=None, kid="trusted-key", **overrides):
        now = datetime.now(UTC)
        claims = {
            "sub": "ca05a7a9-3e5b-4e11-9415-3d403634ce00",
            "email": "farmer@example.com",
            "iss": "http://127.0.0.1:54321/auth/v1",
            "aud": "authenticated", "iat": now,
            "exp": now + timedelta(minutes=5), "aal": "aal1",
            **overrides,
        }
        return jwt.encode(claims, key or self.key, algorithm="ES256", headers={"kid": kid})

    async def verify(self, token):
        with (
            patch.object(auth, "_jwks_client", self.client),
            patch.object(auth.settings, "SUPABASE_URL", "http://127.0.0.1:54321"),
        ):
            return await auth.get_verified_claims(
                HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
            )

    async def rejected(self, token, status):
        with self.assertRaises(HTTPException) as caught:
            await self.verify(token)
        self.assertEqual(caught.exception.status_code, status)

    async def test_redirects_never_fetch_or_trust_destination_keys(self):
        # The redirected server has a valid EC key and matching issuer/audience.
        # An attacker controlling the redirect would bypass signature trust in 2.13.
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status=status):
                self.state["status"] = status
                self.client = jwt.PyJWKClient(self.url, cache_keys=True, timeout=5)
                await self.rejected(self.token(), 503)
                self.assertEqual(self.destination["requests"], 0)

    async def test_direct_jwks_verifies_es256_and_uses_cached_key(self):
        self.assertEqual((await self.verify(self.token()))["aal"], "aal1")
        await self.verify(self.token())
        self.assertEqual(self.state["requests"], 1)
        self.assertEqual(self.destination["requests"], 0)

    async def test_real_transport_keeps_issuer_audience_expiration_and_signature_checks(self):
        await self.verify(self.token())
        for overrides in (
            {"iss": "http://untrusted.invalid/auth/v1"},
            {"aud": "service_role"},
            {"exp": datetime.now(UTC) - timedelta(seconds=1)},
            {"key": ec.generate_private_key(ec.SECP256R1())},
        ):
            with self.subTest(fields=tuple(overrides)):
                await self.rejected(self.token(**overrides), 401)

    async def test_unknown_kids_are_throttled_and_rotation_recovers_after_cooldown(self):
        await self.verify(self.token())
        new_key = ec.generate_private_key(ec.SECP256R1())
        new_jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(new_key.public_key()))
        new_jwk.update(kid="rotated-key", alg="ES256", use="sig")
        self.state["keys"] = [self.jwk, new_jwk]
        for kid in ("unknown-1", "unknown-2", "rotated-key"):
            await self.rejected(self.token(key=new_key, kid=kid), 401)
        self.assertEqual(self.state["requests"], 1)
        # Advance only the transport cooldown clock; HTTP and cryptography stay real.
        clock = SimpleNamespace(monotonic=lambda: advanced_time)
        advanced_time = time.monotonic() + 31
        with patch("jwt.jwks_client.time", clock):
            await self.verify(self.token(key=new_key, kid="rotated-key"))
        self.assertEqual(self.state["requests"], 2)

    async def test_unavailable_endpoint_returns_503(self):
        self.state["status"] = 503
        await self.rejected(self.token(), 503)
        self.assertEqual(self.state["requests"], 1)


if __name__ == "__main__":
    unittest.main()
