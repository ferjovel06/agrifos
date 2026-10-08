import json
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.core import auth
from app.core.config import Settings


class SupabaseJwksConfigurationTests(unittest.TestCase):
    def make_settings(self, **overrides):
        return Settings(
            _env_file=None,
            DATABASE_URL="postgresql+asyncpg://postgres:test@localhost/agrifos_test",
            SUPABASE_JWKS_URL=None,
            **overrides,
        )

    def test_default_jwks_url_preserves_hosted_supabase_configuration(self):
        settings = self.make_settings(SUPABASE_URL="https://example.supabase.co")

        self.assertEqual(
            settings.supabase_jwks_url,
            "https://example.supabase.co/auth/v1/.well-known/jwks.json",
        )

    def test_default_jwks_url_normalizes_a_trailing_slash(self):
        settings = self.make_settings(SUPABASE_URL="https://example.supabase.co/")

        self.assertEqual(
            settings.supabase_jwks_url,
            "https://example.supabase.co/auth/v1/.well-known/jwks.json",
        )

    def test_internal_jwks_url_keeps_the_public_supabase_url(self):
        internal_url = (
            "http://supabase_kong_agrifos:8000/auth/v1/.well-known/jwks.json"
        )
        settings = Settings(
            _env_file=None,
            DATABASE_URL="postgresql+asyncpg://postgres:test@localhost/agrifos_test",
            SUPABASE_URL="http://127.0.0.1:54321",
            SUPABASE_JWKS_URL=internal_url,
        )

        self.assertEqual(settings.supabase_jwks_url, internal_url)
        self.assertEqual(settings.SUPABASE_URL, "http://127.0.0.1:54321")


class VerifiedClaimsCryptographyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.signing_key = ec.generate_private_key(ec.SECP256R1())
        self.public_jwk = json.loads(
            jwt.algorithms.ECAlgorithm.to_jwk(self.signing_key.public_key())
        )
        self.public_jwk.update(kid="local-test-key", alg="ES256", use="sig")
        self.public_url = "http://127.0.0.1:54321"
        self.jwks_client = jwt.PyJWKClient(
            "http://supabase_kong_agrifos:8000/auth/v1/.well-known/jwks.json"
        )
        now = datetime.now(UTC)
        self.claims = {
            "sub": "ca05a7a9-3e5b-4e11-9415-3d403634ce00",
            "email": "farmer@example.com",
            "aud": "authenticated",
            "iss": f"{self.public_url}/auth/v1",
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "aal": "aal1",
        }

    def token(self, *, claims=None, signing_key=None, algorithm="ES256"):
        return jwt.encode(
            self.claims if claims is None else claims,
            self.signing_key if signing_key is None else signing_key,
            algorithm=algorithm,
            headers={"kid": "local-test-key"},
        )

    async def verify(self, token):
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        # Replace only the network fetch; key selection and JWT decoding stay real.
        with (
            patch.object(auth.settings, "SUPABASE_URL", self.public_url),
            patch.object(auth, "_jwks_client", self.jwks_client),
            patch.object(
                self.jwks_client,
                "fetch_data",
                return_value={"keys": [self.public_jwk]},
            ),
        ):
            return await auth.get_verified_claims(credentials)

    async def assert_rejected(self, token):
        with self.assertRaises(HTTPException) as raised:
            await self.verify(token)

        self.assertEqual(raised.exception.status_code, 401)
        self.assertEqual(raised.exception.detail, "Invalid token.")

    async def test_verifies_es256_with_internal_jwks_and_public_issuer(self):
        claims = await self.verify(self.token())

        self.assertEqual(claims["sub"], self.claims["sub"])
        self.assertEqual(claims["iss"], f"{self.public_url}/auth/v1")

    async def test_rejects_a_signature_from_another_key(self):
        other_key = ec.generate_private_key(ec.SECP256R1())

        await self.assert_rejected(self.token(signing_key=other_key))

    async def test_rejects_the_internal_hostname_as_issuer(self):
        claims = {**self.claims, "iss": "http://supabase_kong_agrifos:8000/auth/v1"}

        await self.assert_rejected(self.token(claims=claims))

    async def test_rejects_a_different_audience(self):
        claims = {**self.claims, "aud": "service_role"}

        await self.assert_rejected(self.token(claims=claims))

    async def test_rejects_hs256_even_when_the_key_id_matches(self):
        token = self.token(
            signing_key="local-test-hmac-key-never-used-for-authentication",
            algorithm="HS256",
        )

        await self.assert_rejected(token)

    async def test_rejects_an_expired_token(self):
        claims = {**self.claims, "exp": datetime.now(UTC) - timedelta(minutes=1)}

        await self.assert_rejected(self.token(claims=claims))


if __name__ == "__main__":
    unittest.main()
