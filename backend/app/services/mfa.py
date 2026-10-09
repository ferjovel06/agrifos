from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import UUID, uuid4

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
import pyotp
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import AuthCredential, AuthMfaChallenge, AuthMfaFactor, User
from app.repositories.mfa import get_challenge_account, get_login_factor
from app.services.auth import check_account_access


def password_fingerprint(stored_hash: str) -> str:
    return sha256(stored_hash.encode()).hexdigest()


async def start_login_challenge(db: AsyncSession, credential: AuthCredential) -> AuthMfaChallenge:
    now = datetime.now(timezone.utc)
    check_mfa_lock(credential, now)
    factor = await get_login_factor(db, credential.user_id)
    if factor is None:
        raise HTTPException(503, "No se pudo preparar la verificación en dos pasos.")
    challenge = AuthMfaChallenge(
        id=uuid4(), user_id=credential.user_id, factor_id=factor.id,
        password_fingerprint=password_fingerprint(credential.password_hash),
        expires_at=now + timedelta(seconds=settings.AUTH_MFA_CHALLENGE_SECONDS),
    )
    db.add(challenge)
    await db.commit()
    return challenge


async def verify_login_challenge(db: AsyncSession, challenge_id: UUID, code: str) -> User:
    account = await get_challenge_account(db, challenge_id)
    if account is None:
        raise _invalid_challenge()
    challenge, credential, factor, user = account
    now = datetime.now(timezone.utc)
    _validate_challenge(challenge, credential, now)
    check_mfa_lock(credential, now)
    check_account_access(credential, now)
    counter = matching_counter(factor, code, now)
    if counter is None:
        await record_mfa_failure(db, credential, now)
        raise HTTPException(401, "El código no es válido o ya fue utilizado.")
    factor.last_verified_counter = counter
    challenge.consumed_at = now
    credential.mfa_failed_attempts = 0
    credential.mfa_locked_until = None
    await db.commit()
    return user


def _validate_challenge(challenge: AuthMfaChallenge, credential: AuthCredential, now: datetime):
    if challenge.consumed_at or challenge.expires_at <= now:
        raise _invalid_challenge()
    if not credential.mfa_enabled or not credential.password_hash:
        raise _invalid_challenge()
    if challenge.password_fingerprint != password_fingerprint(credential.password_hash):
        raise _invalid_challenge()


def _invalid_challenge() -> HTTPException:
    return HTTPException(401, "La verificación venció o no es válida. Inicia sesión de nuevo.")


def check_mfa_lock(credential: AuthCredential, now: datetime):
    if credential.mfa_locked_until and credential.mfa_locked_until > now:
        raise HTTPException(429, "Demasiados intentos de verificación. Intenta de nuevo más tarde.")


def matching_counter(factor: AuthMfaFactor, code: str, now: datetime) -> int | None:
    try:
        cipher = Fernet(settings.AUTH_MFA_ENCRYPTION_KEY.get_secret_value().encode())
        secret = cipher.decrypt(factor.secret_ciphertext.encode()).decode()
        if not secret:
            raise ValueError("Empty TOTP secret.")
        totp = pyotp.TOTP(secret)
        current_counter = totp.timecode(now)
        for counter in range(current_counter - 1, current_counter + 2):
            if factor.last_verified_counter is not None and counter <= factor.last_verified_counter:
                continue
            if pyotp.utils.strings_equal(totp.generate_otp(counter), code):
                return counter
    except (InvalidToken, ValueError, TypeError, UnicodeError) as error:
        raise HTTPException(503, "No se pudo validar el segundo factor.") from error
    return None


async def record_mfa_failure(db: AsyncSession, credential: AuthCredential, now: datetime):
    if credential.mfa_locked_until and credential.mfa_locked_until <= now:
        credential.mfa_failed_attempts = 0
        credential.mfa_locked_until = None
    credential.mfa_failed_attempts += 1
    if credential.mfa_failed_attempts >= settings.AUTH_MAX_MFA_ATTEMPTS:
        credential.mfa_locked_until = now + timedelta(seconds=settings.AUTH_MFA_LOCK_SECONDS)
    await db.commit()
