from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
import pyotp

from app.core.config import Settings, settings
from app.core.tokens import verify_access_token
from app.db.session import get_db
from app.main import app
from app.models import AuthCredential, AuthMfaChallenge, AuthMfaFactor
from app.services.mfa import matching_counter, password_fingerprint, start_login_challenge, verify_login_challenge


class MfaServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 8, 12, 0, 15, tzinfo=timezone.utc)
        self.db = AsyncMock()
        self.db.add = Mock()
        self.user = SimpleNamespace(id=uuid4(), email="mfa@example.com")
        self.secret = pyotp.random_base32()
        self.totp = pyotp.TOTP(self.secret)
        self.key = Fernet.generate_key()
        self.credential = AuthCredential(
            user_id=self.user.id, password_hash="test-password-hash",
            email_confirmed=True, mfa_enabled=True,
            mfa_failed_attempts=0, failed_attempts=0,
        )
        self.factor = AuthMfaFactor(
            id=uuid4(), user_id=self.user.id,
            secret_ciphertext=Fernet(self.key).encrypt(self.secret.encode()).decode(),
        )
        self.challenge = AuthMfaChallenge(
            id=uuid4(), user_id=self.user.id, factor_id=self.factor.id,
            password_fingerprint=password_fingerprint(self.credential.password_hash),
            expires_at=self.now + timedelta(minutes=5),
        )
        for item in (
            patch.object(settings, "AUTH_MFA_ENCRYPTION_KEY", SecretStr(self.key.decode())),
            patch("app.services.mfa.get_challenge_account", new=AsyncMock(return_value=(self.challenge,self.credential,self.factor,self.user))),
            patch("app.services.mfa.get_login_factor", new=AsyncMock(return_value=self.factor)),
            patch("app.services.mfa.datetime"),
        ):
            value = item.start()
            if getattr(item, "attribute", None) == "datetime":
                value.now.return_value = self.now
            self.addCleanup(item.stop)
        allowed_codes = {self.totp.at(self.now + timedelta(seconds=offset)) for offset in (-30,0,30)}
        self.wrong_code = next(f"{value:06d}" for value in range(10) if f"{value:06d}" not in allowed_codes)

    async def denied(self, status, code=None):
        with self.assertRaises(HTTPException) as raised:
            await verify_login_challenge(self.db, self.challenge.id, code or self.totp.at(self.now))
        self.assertEqual(raised.exception.status_code,status)

    async def test_password_challenge_is_bound_to_factor_hash_and_expiration(self):
        challenge = await start_login_challenge(self.db,self.credential)
        self.assertEqual(challenge.factor_id,self.factor.id)
        self.assertEqual(challenge.password_fingerprint,password_fingerprint(self.credential.password_hash))
        self.assertEqual((challenge.expires_at-self.now).total_seconds(),settings.AUTH_MFA_CHALLENGE_SECONDS)
        self.db.add.assert_called_once_with(challenge)
        self.db.commit.assert_awaited_once()

    async def test_valid_code_consumes_challenge_and_resets_failures(self):
        self.credential.mfa_failed_attempts = 2
        user = await verify_login_challenge(self.db,self.challenge.id,self.totp.at(self.now))
        self.assertIs(user,self.user)
        self.assertEqual(self.factor.last_verified_counter,self.totp.timecode(self.now))
        self.assertEqual(self.challenge.consumed_at,self.now)
        self.assertEqual(self.credential.mfa_failed_attempts,0)
        self.db.commit.assert_awaited_once()

    async def test_consumed_or_expired_challenge_cannot_be_reused(self):
        self.challenge.consumed_at = self.now
        await self.denied(401)
        self.challenge.consumed_at = None
        self.challenge.expires_at = self.now
        await self.denied(401)
        self.db.commit.assert_not_awaited()

    async def test_same_totp_cannot_be_reused_on_another_challenge(self):
        self.factor.last_verified_counter = self.totp.timecode(self.now)
        await self.denied(401)
        self.assertIsNone(self.challenge.consumed_at)
        self.assertEqual(self.credential.mfa_failed_attempts,1)

    async def test_password_change_or_disabled_mfa_invalidates_challenge(self):
        self.credential.password_hash = "new-hash"
        await self.denied(401)
        self.credential.password_hash = "test-password-hash"
        self.credential.mfa_enabled = False
        await self.denied(401)
        self.db.commit.assert_not_awaited()

    async def test_unknown_challenge_is_rejected(self):
        with patch("app.services.mfa.get_challenge_account",new=AsyncMock(return_value=None)):
            await self.denied(401)

    async def test_invalid_codes_lock_account_across_challenges(self):
        self.credential.mfa_failed_attempts = settings.AUTH_MAX_MFA_ATTEMPTS-1
        await self.denied(401,self.wrong_code)
        self.assertGreater(self.credential.mfa_locked_until,self.now)
        await self.denied(429)
        with self.assertRaises(HTTPException) as raised:
            await start_login_challenge(self.db,self.credential)
        self.assertEqual(raised.exception.status_code,429)

    async def test_expired_mfa_lock_starts_new_attempt_window(self):
        self.credential.mfa_failed_attempts = 5
        self.credential.mfa_locked_until = self.now-timedelta(seconds=1)
        await self.denied(401,self.wrong_code)
        self.assertEqual(self.credential.mfa_failed_attempts,1)
        self.assertIsNone(self.credential.mfa_locked_until)

    async def test_banned_or_unconfirmed_account_cannot_complete_mfa(self):
        self.credential.banned_until = self.now+timedelta(days=1)
        await self.denied(403)
        self.credential.banned_until = None
        self.credential.email_confirmed = False
        await self.denied(403)

    async def test_corrupt_ciphertext_fails_closed(self):
        self.factor.secret_ciphertext = "corrupt-ciphertext"
        await self.denied(503)
        self.assertIsNone(self.challenge.consumed_at)
        self.db.commit.assert_not_awaited()

    async def test_missing_factor_does_not_issue_a_challenge(self):
        with patch("app.services.mfa.get_login_factor",new=AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as raised:
                await start_login_challenge(self.db,self.credential)
        self.assertEqual(raised.exception.status_code,503)
        self.db.add.assert_not_called()

    def test_clock_skew_window_accepts_adjacent_steps_but_not_older_codes(self):
        for offset in (-30,0,30):
            self.assertEqual(matching_counter(self.factor,self.totp.at(self.now+timedelta(seconds=offset)),self.now),self.totp.timecode(self.now)+offset//30)
        self.factor.last_verified_counter = self.totp.timecode(self.now)+1
        self.assertIsNone(matching_counter(self.factor,self.totp.at(self.now),self.now))


class MfaRouteTests(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(app)
        self.db=AsyncMock()
        app.dependency_overrides[get_db]=lambda:self.db
        self.addCleanup(app.dependency_overrides.pop,get_db)
        native=patch.object(settings,"AUTH_PROVIDER","native")
        native.start()
        self.addCleanup(native.stop)

    def test_mfa_login_returns_only_challenge_and_never_access_token(self):
        user=SimpleNamespace(id=uuid4(),email="mfa@example.com")
        credential=SimpleNamespace(mfa_enabled=True)
        challenge=SimpleNamespace(id=uuid4())
        with patch("app.routers.auth.authenticate_user",new=AsyncMock(return_value=(user,credential))), patch("app.routers.auth.start_login_challenge",new=AsyncMock(return_value=challenge)), patch("app.routers.auth.create_access_token") as token:
            response=self.client.post('/auth/login',json={'email':user.email,'password':'test'})
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json()['mfa_required'])
        self.assertEqual(response.json()['challenge_id'],str(challenge.id))
        self.assertNotIn('access_token',response.json())
        token.assert_not_called()

    def test_successful_mfa_issues_aal2_token(self):
        user=SimpleNamespace(id=uuid4(),email="mfa@example.com")
        with patch.object(settings,"AUTH_JWT_SECRET",SecretStr('test-only-key-with-at-least-32-bytes')), patch("app.routers.auth.verify_login_challenge",new=AsyncMock(return_value=user)):
            response=self.client.post('/auth/mfa/verify',json={'challenge_id':str(uuid4()),'code':'123456'})
            claims=verify_access_token(response.json()['access_token'])
        self.assertEqual(response.status_code,200)
        self.assertEqual(claims['aal'],'aal2')
        self.assertEqual(response.headers['cache-control'],'no-store')

    def test_invalid_code_shapes_are_rejected_before_verification(self):
        with patch("app.routers.auth.verify_login_challenge",new=AsyncMock()) as verify:
            for code in ('12345','1234567','abcdef','١٢٣٤٥٦','123456\n'):
                self.assertEqual(self.client.post('/auth/mfa/verify',json={'challenge_id':str(uuid4()),'code':code}).status_code,422)
        verify.assert_not_awaited()

    def test_mfa_endpoint_is_disabled_with_supabase_provider(self):
        with patch.object(settings,'AUTH_PROVIDER','supabase'):
            response=self.client.post('/auth/mfa/verify',json={'challenge_id':str(uuid4()),'code':'123456'})
        self.assertEqual(response.status_code,503)

    def test_native_configuration_requires_a_valid_mfa_key(self):
        with self.assertRaises(ValidationError) as raised:
            Settings(_env_file=None,DATABASE_URL='postgresql://private:test',SUPABASE_URL='https://example.supabase.co',AUTH_PROVIDER='native',AUTH_JWT_SECRET='test-only-key-with-at-least-32-bytes',AUTH_MFA_ENCRYPTION_KEY='invalid')
        self.assertNotIn('postgresql://private:test',str(raised.exception))
