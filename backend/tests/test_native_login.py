from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import bcrypt
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
import jwt
from pydantic import SecretStr, ValidationError

from app.core.auth import get_verified_claims
from app.core.config import Settings, settings
from app.core.passwords import password_hash
from app.core.tokens import create_access_token, verify_access_token
from app.db.session import get_db
from app.main import app
from app.models import AuthCredential
from app.services.auth import authenticate_user


TEST_SECRET = "test-only-signing-key-with-at-least-32-bytes"


class LoginServiceTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = "migration-test-password"
        cls.legacy_hash = bcrypt.hashpw(cls.password.encode(), bcrypt.gensalt(rounds=4, prefix=b"2a")).decode()

    def setUp(self):
        self.db = AsyncMock()
        self.user = SimpleNamespace(id=uuid4(), email="farmer@example.com")
        self.credential = AuthCredential(
            user_id=self.user.id, password_hash=self.legacy_hash,
            email_confirmed=True, mfa_enabled=False, failed_attempts=0,
        )
        self.lookup = patch("app.services.auth.get_login_account", new=AsyncMock(return_value=(self.credential, self.user)))
        self.lookup.start()
        self.addCleanup(self.lookup.stop)

    async def assert_denied(self, password, expected_status):
        with self.assertRaises(HTTPException) as raised:
            await authenticate_user(self.db, self.user.email, password)
        self.assertEqual(raised.exception.status_code, expected_status)
        return raised.exception

    async def test_valid_legacy_login_upgrades_hash_and_clears_failed_attempts(self):
        self.credential.failed_attempts = 2
        result = await authenticate_user(self.db, self.user.email, self.password)
        self.assertIs(result, self.user)
        self.assertTrue(self.credential.password_hash.startswith("$argon2id$"))
        self.assertEqual(self.credential.failed_attempts, 0)
        self.db.commit.assert_awaited_once()

    async def test_invalid_password_is_generic_and_preserves_hash(self):
        error = await self.assert_denied("wrong", 401)
        self.assertEqual(error.detail, "Correo o contraseña incorrectos.")
        self.assertEqual(self.credential.password_hash, self.legacy_hash)
        self.assertEqual(self.credential.failed_attempts, 1)
        self.db.commit.assert_awaited_once()

    async def test_unknown_email_returns_the_same_error(self):
        with patch("app.services.auth.get_login_account", new=AsyncMock(return_value=None)):
            error = await self.assert_denied("wrong", 401)
        self.assertEqual(error.detail, "Correo o contraseña incorrectos.")
        self.db.commit.assert_not_awaited()

    async def test_repeated_failures_lock_the_account(self):
        self.credential.failed_attempts = settings.AUTH_MAX_LOGIN_ATTEMPTS - 1
        await self.assert_denied("wrong", 401)
        self.assertGreater(self.credential.locked_until, datetime.now(timezone.utc))
        with patch("app.services.auth.asyncio.to_thread", new=AsyncMock()) as verify:
            await self.assert_denied(self.password, 429)
        verify.assert_not_awaited()

    async def test_expired_lock_starts_a_new_attempt_window(self):
        self.credential.failed_attempts = settings.AUTH_MAX_LOGIN_ATTEMPTS
        self.credential.locked_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        await self.assert_denied("wrong", 401)
        self.assertEqual(self.credential.failed_attempts, 1)
        self.assertIsNone(self.credential.locked_until)

    async def test_unconfirmed_account_cannot_login(self):
        self.credential.email_confirmed = False
        await self.assert_denied(self.password, 403)
        self.db.commit.assert_not_awaited()

    async def test_banned_account_cannot_login(self):
        self.credential.banned_until = datetime.now(timezone.utc) + timedelta(days=1)
        await self.assert_denied(self.password, 403)
        self.db.commit.assert_not_awaited()

    async def test_mfa_account_cannot_bypass_second_factor(self):
        self.credential.mfa_enabled = True
        error = await self.assert_denied(self.password, 403)
        self.assertEqual(error.detail["code"], "mfa_required")
        self.assertEqual(self.credential.password_hash, self.legacy_hash)
        self.db.commit.assert_not_awaited()

    async def test_missing_or_invalid_hash_is_rejected(self):
        for value in (None, "invalid-hash"):
            with self.subTest(value=value):
                self.credential.password_hash = value
                await self.assert_denied(self.password, 401)

    async def test_long_input_for_legacy_bcrypt_does_not_crash(self):
        await self.assert_denied("x" * 100, 401)


class NativeTokenTests(unittest.TestCase):
    def setUp(self):
        secret_patch = patch.object(settings, "AUTH_JWT_SECRET", SecretStr(TEST_SECRET))
        secret_patch.start()
        self.addCleanup(secret_patch.stop)
        self.user = SimpleNamespace(id=uuid4(), email="farmer@example.com")

    def test_token_preserves_identity_and_has_unique_id(self):
        first = verify_access_token(create_access_token(self.user))
        second = verify_access_token(create_access_token(self.user))
        self.assertEqual(first["sub"], str(self.user.id))
        self.assertEqual(first["email"], self.user.email)
        self.assertEqual(first["aal"], "aal1")
        self.assertEqual(first["exp"] - first["iat"], settings.AUTH_ACCESS_TOKEN_SECONDS)
        self.assertNotEqual(first["jti"], second["jti"])

    def test_expired_or_wrong_purpose_issuer_audience_and_identity_are_rejected(self):
        claims = verify_access_token(create_access_token(self.user))
        cases = [{"exp": 1}, {"type": "refresh"}, {"iss": "other"}, {"aud": "other"}, {"sub": "invalid"}, {"aal": "aal3"}]
        for change in cases:
            with self.subTest(change=change):
                token = jwt.encode({**claims, **change}, TEST_SECRET, algorithm="HS256")
                with self.assertRaises(jwt.InvalidTokenError):
                    verify_access_token(token)

    def test_missing_expiration_wrong_signature_and_unsigned_tokens_are_rejected(self):
        claims = verify_access_token(create_access_token(self.user))
        claims.pop("exp")
        tokens = [
            jwt.encode(claims, TEST_SECRET, algorithm="HS256"),
            jwt.encode(claims, "different-key-of-at-least-32-bytes", algorithm="HS256"),
            jwt.encode(claims, None, algorithm="none"),
        ]
        for token in tokens:
            with self.assertRaises(jwt.InvalidTokenError):
                verify_access_token(token)

    def test_native_configuration_requires_a_strong_secret(self):
        with self.assertRaises(ValidationError):
            Settings(_env_file=None, DATABASE_URL="postgresql://test", SUPABASE_URL="https://example.supabase.co", AUTH_PROVIDER="native", AUTH_JWT_SECRET="short")


class LoginRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: self.db
        self.addCleanup(app.dependency_overrides.pop, get_db)

    def test_disabled_native_login_does_not_authenticate(self):
        with patch.object(settings, "AUTH_PROVIDER", "supabase"), patch("app.routers.auth.authenticate_user", new=AsyncMock()) as authenticate:
            response = self.client.post("/auth/login", json={"email": "farmer@example.com", "password": "test"})
        self.assertEqual(response.status_code, 503)
        authenticate.assert_not_awaited()

    def test_login_returns_a_valid_noncacheable_bearer_token(self):
        user = SimpleNamespace(id=uuid4(), email="farmer@example.com")
        with patch.object(settings, "AUTH_PROVIDER", "native"), patch.object(settings, "AUTH_JWT_SECRET", SecretStr(TEST_SECRET)), patch("app.routers.auth.authenticate_user", new=AsyncMock(return_value=user)):
            response = self.client.post("/auth/login", json={"email": user.email, "password": "test"})
            claims = verify_access_token(response.json()["access_token"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.json()["token_type"], "bearer")
        self.assertEqual(claims["sub"], str(user.id))

    def test_invalid_email_and_oversized_password_are_rejected(self):
        for payload in ({"email": "not-email", "password": "test"}, {"email": "farmer@example.com", "password": "x" * 1025}):
            self.assertEqual(self.client.post("/auth/login", json=payload).status_code, 422)


class NativeVerificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_token_uses_local_key_without_contacting_supabase(self):
        user = SimpleNamespace(id=uuid4(), email="farmer@example.com")
        with patch.object(settings, "AUTH_PROVIDER", "native"), patch.object(settings, "AUTH_JWT_SECRET", SecretStr(TEST_SECRET)), patch("app.core.auth.asyncio.to_thread", new=AsyncMock()) as remote:
            token = create_access_token(user)
            claims = await get_verified_claims(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token))
        self.assertEqual(claims["sub"], str(user.id))
        remote.assert_not_awaited()
