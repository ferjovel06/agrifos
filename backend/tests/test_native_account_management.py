from datetime import datetime, timedelta, timezone
from hashlib import sha256
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4
from xml.etree import ElementTree

from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr
import pyotp

from app.core.auth import get_current_user, get_verified_claims
from app.core.config import settings
from app.core.passwords import password_hash
from app.db.session import get_db
from app.main import app
from app.models import AuthCredential, AuthEmailToken, AuthMfaFactor, User
from app.services import auth_accounts, mfa_management
from app.services.auth_mail import get_auth_mailer, SmtpAuthMailer
from app.services.mfa import password_fingerprint


class AccountServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = AsyncMock()
        self.db.add = Mock()
        self.mailer = SimpleNamespace(send=AsyncMock())
        self.user = User(id=uuid4(), name="Test user", email="test@example.com", role="farmer")
        self.credential = AuthCredential(user_id=self.user.id, password_hash="stored-hash", email_confirmed=True,
                                         mfa_enabled=True, failed_attempts=3)
        self.token = "a" * 43
        self.now = datetime.now(timezone.utc)
        self.proof = AuthEmailToken(digest=sha256(self.token.encode()).hexdigest(), user_id=self.user.id,
            purpose="recovery", password_fingerprint=password_fingerprint(self.credential.password_hash),
            created_at=self.now, expires_at=self.now + timedelta(minutes=30))

    async def test_registration_creates_only_farmer_and_never_stores_raw_password_or_email_token(self):
        with patch("app.services.auth_accounts.get_login_account", new=AsyncMock(return_value=None)), \
             patch("app.services.auth_accounts.latest_email_proof", new=AsyncMock(return_value=None)):
            await auth_accounts.register_account(self.db, " Test user ", "TEST@example.com", "Test-password-123", self.mailer)
        items = [call.args[0] for call in self.db.add.call_args_list]
        user = next(item for item in items if isinstance(item, User))
        credential = next(item for item in items if isinstance(item, AuthCredential))
        proof = next(item for item in items if isinstance(item, AuthEmailToken))
        self.assertEqual(user.role, "farmer")
        self.assertEqual(user.email, "test@example.com")
        self.assertFalse(credential.email_confirmed)
        self.assertTrue(password_hash.verify("Test-password-123", credential.password_hash))
        sent = self.mailer.send.call_args.args[2]
        self.assertEqual(proof.digest, sha256(sent.encode()).hexdigest())
        self.assertNotEqual(proof.digest, sent)

    async def test_existing_registration_does_not_overwrite_account(self):
        with patch("app.services.auth_accounts.get_login_account", new=AsyncMock(return_value=(self.credential,self.user))):
            await auth_accounts.register_account(self.db, "Other name", self.user.email, "Different-password-123", self.mailer)
        self.db.add.assert_not_called()
        self.mailer.send.assert_not_awaited()
        self.assertEqual(self.credential.password_hash, "stored-hash")

    async def test_unknown_and_unconfirmed_recovery_do_not_send_email(self):
        for account in [None, (self.credential,self.user)]:
            self.credential.email_confirmed = False
            with patch("app.services.auth_accounts.get_login_account", new=AsyncMock(return_value=account)):
                await auth_accounts.request_account_email(self.db,self.user.email,"recovery",self.mailer)
        self.mailer.send.assert_not_awaited()

    async def test_email_cooldown_and_delivery_failure(self):
        with patch("app.services.auth_accounts.latest_email_proof", new=AsyncMock(return_value=self.proof)):
            await auth_accounts.send_account_email(self.db,self.credential,self.user,"recovery",self.mailer)
        self.mailer.send.assert_not_awaited()
        self.mailer.send.side_effect = HTTPException(503,"Mail unavailable")
        with patch("app.services.auth_accounts.latest_email_proof", new=AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException):
                await auth_accounts.send_account_email(self.db,self.credential,self.user,"recovery",self.mailer)
        self.db.rollback.assert_awaited_once()
        self.db.commit.assert_not_awaited()

    async def test_reset_revokes_tokens_consumes_proof_and_preserves_mfa(self):
        with patch("app.services.auth_accounts.get_email_proof", new=AsyncMock(return_value=(self.proof,self.credential,self.user))):
            await auth_accounts.redeem_email(self.db,self.token,"recovery","New-password-123")
        self.assertTrue(password_hash.verify("New-password-123",self.credential.password_hash))
        self.assertIsNotNone(self.credential.tokens_valid_after)
        self.assertIsNotNone(self.proof.consumed_at)
        self.assertTrue(self.credential.mfa_enabled)
        self.assertEqual(self.credential.failed_attempts,0)

    async def test_expired_consumed_changed_password_or_banned_proofs_are_rejected(self):
        scenarios = ["expired","consumed","password_changed","banned"]
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                self.proof.expires_at = self.now + timedelta(minutes=30)
                self.proof.consumed_at = None
                self.credential.password_hash = "stored-hash"
                self.credential.banned_until = None
                if scenario == "expired": self.proof.expires_at = self.now
                if scenario == "consumed": self.proof.consumed_at = self.now
                if scenario == "password_changed": self.credential.password_hash = "new-hash"
                if scenario == "banned": self.credential.banned_until = self.now + timedelta(days=1)
                with patch("app.services.auth_accounts.get_email_proof", new=AsyncMock(return_value=(self.proof,self.credential,self.user))):
                    with self.assertRaises(HTTPException) as raised:
                        await auth_accounts.redeem_email(self.db,self.token,"recovery","New-password-123")
                self.assertEqual(raised.exception.status_code,401)
        self.db.commit.assert_not_awaited()

    async def test_confirmation_enables_email_without_issuing_session(self):
        self.credential.email_confirmed = False
        with patch("app.services.auth_accounts.get_email_proof", new=AsyncMock(return_value=(self.proof,self.credential,self.user))) as lookup:
            await auth_accounts.redeem_email(self.db,self.token,"confirmation")
        self.assertTrue(self.credential.email_confirmed)
        self.assertIsNotNone(self.proof.consumed_at)
        self.assertEqual(lookup.call_args.args[2],"confirmation")

    async def test_short_password_fails_before_any_database_or_mail_operation(self):
        with self.assertRaises(HTTPException) as raised:
            await auth_accounts.register_account(self.db,"Test",self.user.email,"short",self.mailer)
        self.assertEqual(raised.exception.status_code,422)
        self.db.execute.assert_not_awaited()

    async def test_password_change_uses_login_lockout_and_keeps_transaction_open(self):
        with patch("app.services.auth_accounts.get_account", new=AsyncMock(return_value=(self.credential,self.user))), \
             patch("app.services.auth_accounts.authenticate_user", new=AsyncMock()) as authenticate:
            await auth_accounts.change_password(self.db,self.user.id,"Old-password-123","New-password-123")
        authenticate.assert_awaited_once_with(self.db,self.user.email,"Old-password-123",commit=False)
        self.assertIsNotNone(self.credential.tokens_valid_after)
        self.db.commit.assert_awaited_once()


class MfaManagementTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = AsyncMock()
        self.db.add = Mock()
        self.user = User(id=uuid4(),name="Test user",email="test@example.com")
        self.credential = AuthCredential(user_id=self.user.id,password_hash="hash",email_confirmed=True,
            mfa_enabled=False,mfa_failed_attempts=0)
        self.key = Fernet.generate_key()
        self.secret = pyotp.random_base32()
        self.factor = AuthMfaFactor(id=uuid4(),user_id=self.user.id,verified=False,
            secret_ciphertext=Fernet(self.key).encrypt(self.secret.encode()).decode(),
            enrollment_expires_at=datetime.now(timezone.utc)+timedelta(minutes=10))
        for item in [patch.object(settings,"AUTH_MFA_ENCRYPTION_KEY",SecretStr(self.key.decode())),
                     patch("app.services.mfa_management.get_account",new=AsyncMock(return_value=(self.credential,self.user))),
                     patch("app.services.mfa_management.get_factor",new=AsyncMock(return_value=self.factor))]:
            item.start()
            self.addCleanup(item.stop)

    async def test_enrollment_returns_svg_and_encrypted_pending_factor(self):
        result = await mfa_management.enroll_mfa(self.db,self.user.id)
        factor = self.db.add.call_args.args[0]
        self.assertFalse(factor.verified)
        self.assertFalse(self.credential.mfa_enabled)
        self.assertNotEqual(factor.secret_ciphertext,result["secret"])
        self.assertEqual(Fernet(self.key).decrypt(factor.secret_ciphertext.encode()).decode(),result["secret"])
        self.assertTrue(ElementTree.fromstring(result["qr_code"]).tag.endswith("svg"))

    async def test_valid_enrollment_proof_activates_mfa_and_revokes_old_sessions(self):
        user = await mfa_management.confirm_mfa(self.db,self.user.id,self.factor.id,pyotp.TOTP(self.secret).now())
        self.assertIs(user,self.user)
        self.assertTrue(self.factor.verified)
        self.assertTrue(self.credential.mfa_enabled)
        self.assertIsNone(self.factor.enrollment_expires_at)
        self.assertIsNotNone(self.credential.tokens_valid_after)
        self.assertIsNotNone(self.factor.last_verified_counter)

    async def test_expired_missing_already_verified_and_other_user_factors_fail(self):
        self.factor.enrollment_expires_at = datetime.now(timezone.utc)-timedelta(seconds=1)
        with self.assertRaises(HTTPException):
            await mfa_management.confirm_mfa(self.db,self.user.id,self.factor.id,"123456")
        with patch("app.services.mfa_management.get_factor",new=AsyncMock(return_value=None)) as lookup:
            with self.assertRaises(HTTPException):
                await mfa_management.confirm_mfa(self.db,self.user.id,self.factor.id,"123456")
            lookup.assert_awaited_once_with(self.db,self.user.id,self.factor.id)
        self.factor.verified = True
        with self.assertRaises(HTTPException):
            await mfa_management.cancel_mfa(self.db,self.user.id,self.factor.id)
        self.db.delete.assert_not_awaited()

    async def test_new_enrollment_does_not_bypass_global_otp_lock(self):
        self.credential.mfa_locked_until = datetime.now(timezone.utc)+timedelta(minutes=5)
        with self.assertRaises(HTTPException) as raised:
            await mfa_management.enroll_mfa(self.db,self.user.id)
        self.assertEqual(raised.exception.status_code,429)
        self.db.add.assert_not_called()

    async def test_disable_removes_factors_and_revokes_sessions(self):
        self.credential.mfa_enabled = True
        await mfa_management.disable_mfa(self.db,self.user.id)
        self.assertFalse(self.credential.mfa_enabled)
        self.assertIsNotNone(self.credential.tokens_valid_after)
        self.db.execute.assert_awaited_once()


class NativeSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_revoked_token_cannot_access_profile_even_at_aal2(self):
        now = datetime.now(timezone.utc)
        credential = AuthCredential(user_id=uuid4(),email_confirmed=True,mfa_enabled=True,tokens_valid_after=now)
        user = User(id=credential.user_id,name="Test",email="test@example.com")
        claims = {"sub":str(user.id),"email":user.email,"aal":"aal2","iat":now.timestamp()}
        with patch.object(settings,"AUTH_PROVIDER","native"), \
             patch("app.core.auth.get_account",new=AsyncMock(return_value=(credential,user))):
            with self.assertRaises(HTTPException) as raised:
                await get_current_user(claims,AsyncMock())
            self.assertEqual(raised.exception.status_code,401)
            claims["iat"] += 1
            self.assertIs(await get_current_user(claims,AsyncMock()),user)


class AccountRouterTests(unittest.TestCase):
    def setUp(self):
        self.db = AsyncMock()
        self.mailer = SimpleNamespace(send=AsyncMock())
        self.user = User(id=uuid4(),email="test@example.com",name="Test")
        async def database(): yield self.db
        app.dependency_overrides[get_db] = database
        app.dependency_overrides[get_auth_mailer] = lambda: self.mailer
        self.addCleanup(app.dependency_overrides.clear)
        item = patch.object(settings,"AUTH_PROVIDER","native")
        item.start()
        self.addCleanup(item.stop)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_registration_rejects_role_escalation(self):
        response = self.client.post("/auth/register",json={"name":"Test","email":self.user.email,"password":"Test-password-123","role":"admin"})
        self.assertEqual(response.status_code,422)

    def test_email_request_response_never_exposes_token_or_account_existence(self):
        with patch("app.services.auth_accounts.request_account_email",new=AsyncMock()):
            response = self.client.post("/auth/password/forgot",json={"email":self.user.email})
        self.assertEqual(response.status_code,202)
        self.assertEqual(list(response.json()),["message"])
        self.assertEqual(response.headers["cache-control"],"no-store")

    def test_mfa_disable_requires_aal2(self):
        app.dependency_overrides[get_current_user] = lambda: self.user
        app.dependency_overrides[get_verified_claims] = lambda: {"aal":"aal1"}
        with patch("app.services.mfa_management.disable_mfa",new=AsyncMock()) as disable:
            self.assertEqual(self.client.post("/auth/mfa/disable",json={}).status_code,403)
        disable.assert_not_awaited()

    def test_unconfigured_mail_is_reported_without_creating_account(self):
        del app.dependency_overrides[get_auth_mailer]
        with patch.object(settings,"SMTP_HOST",""),patch("app.services.auth_accounts.register_account",new=AsyncMock()) as register:
            response = self.client.post("/auth/register",json={"name":"Test","email":self.user.email,"password":"Test-password-123"})
        self.assertEqual(response.status_code,503)
        register.assert_not_awaited()

    def test_new_endpoints_are_disabled_for_supabase_mode(self):
        with patch.object(settings,"AUTH_PROVIDER","supabase"):
            response = self.client.post("/auth/password/reset",json={"token":"a"*43,"new_password":"New-password-123"})
        self.assertEqual(response.status_code,503)


class MailTests(unittest.IsolatedAsyncioTestCase):
    async def test_smtp_uses_tls_and_does_not_put_token_in_mail_subject(self):
        with patch.object(settings,"SMTP_SECURITY","starttls"), \
             patch.object(settings,"SMTP_HOST","smtp.example.com"), \
             patch.object(settings,"SMTP_FROM","auth@example.com"), \
             patch("app.services.auth_mail.smtplib.SMTP") as transport:
            await SmtpAuthMailer().send("test@example.com","recovery","private-test-token")
        smtp = transport.return_value.__enter__.return_value
        smtp.starttls.assert_called_once()
        message = smtp.send_message.call_args.args[0]
        self.assertNotIn("private-test-token",message["Subject"])
        self.assertIn("type=recovery&token=private-test-token",message.get_content())
