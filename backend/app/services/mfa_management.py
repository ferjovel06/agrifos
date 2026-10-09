from datetime import datetime, timedelta, timezone
from io import BytesIO
from uuid import UUID, uuid4

from cryptography.fernet import Fernet
from fastapi import HTTPException
import pyotp
import qrcode
from qrcode.image.svg import SvgPathImage
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import AuthMfaFactor
from app.repositories.auth_management import get_account, get_factor
from app.services.auth import check_account_access
from app.services.mfa import check_mfa_lock, matching_counter, record_mfa_failure


async def _account(db: AsyncSession, user_id: UUID):
    account = await get_account(db, user_id)
    if account is None:
        raise HTTPException(401, "Tu sesión venció. Inicia sesión de nuevo.")
    check_account_access(account[0], datetime.now(timezone.utc))
    return account


async def mfa_status(db: AsyncSession, user_id: UUID) -> bool:
    credential, _ = await _account(db, user_id)
    return credential.mfa_enabled


async def enroll_mfa(db: AsyncSession, user_id: UUID) -> dict:
    credential, user = await _account(db, user_id)
    if credential.mfa_enabled:
        raise HTTPException(409, "Ya existe un autenticador configurado para esta cuenta.")
    check_mfa_lock(credential, datetime.now(timezone.utc))
    secret = pyotp.random_base32()
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=settings.AUTH_MFA_ISSUER)
    image = qrcode.make(uri, image_factory=SvgPathImage)
    output = BytesIO()
    image.save(output)
    await db.execute(delete(AuthMfaFactor).where(AuthMfaFactor.user_id == user_id, AuthMfaFactor.verified.is_(False)))
    factor = AuthMfaFactor(id=uuid4(), user_id=user_id, verified=False,
        secret_ciphertext=Fernet(settings.AUTH_MFA_ENCRYPTION_KEY.get_secret_value().encode()).encrypt(secret.encode()).decode(),
        enrollment_expires_at=datetime.now(timezone.utc) + timedelta(seconds=settings.AUTH_MFA_ENROLLMENT_SECONDS))
    db.add(factor)
    await db.commit()
    return {"factor_id": factor.id, "qr_code": output.getvalue().decode(), "secret": secret}


async def confirm_mfa(db: AsyncSession, user_id: UUID, factor_id: UUID, code: str):
    credential, user = await _account(db, user_id)
    factor = await get_factor(db, user_id, factor_id)
    now = datetime.now(timezone.utc)
    if credential.mfa_enabled or factor is None or factor.verified or not factor.enrollment_expires_at or factor.enrollment_expires_at <= now:
        raise HTTPException(401, "La configuración venció o no es válida. Iníciala de nuevo.")
    check_mfa_lock(credential, now)
    counter = matching_counter(factor, code, now)
    if counter is None:
        await record_mfa_failure(db, credential, now)
        raise HTTPException(401, "El código no es válido o ya fue utilizado.")
    factor.last_verified_counter = counter
    factor.verified = True
    factor.enrollment_expires_at = None
    credential.mfa_enabled = True
    credential.mfa_failed_attempts = 0
    credential.mfa_locked_until = None
    credential.tokens_valid_after = now
    await db.commit()
    return user


async def cancel_mfa(db: AsyncSession, user_id: UUID, factor_id: UUID):
    await _account(db, user_id)
    factor = await get_factor(db, user_id, factor_id)
    if factor and factor.verified:
        raise HTTPException(409, "Usa la opción de desactivar para quitar el autenticador activo.")
    if factor:
        await db.delete(factor)
    await db.commit()


async def disable_mfa(db: AsyncSession, user_id: UUID):
    credential, user = await _account(db, user_id)
    await db.execute(delete(AuthMfaFactor).where(AuthMfaFactor.user_id == user_id))
    credential.mfa_enabled = False
    credential.tokens_valid_after = datetime.now(timezone.utc)
    credential.mfa_failed_attempts = 0
    credential.mfa_locked_until = None
    await db.commit()
    return user
