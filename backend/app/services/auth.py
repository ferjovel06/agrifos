import asyncio
from datetime import datetime, timedelta, timezone
import secrets

from fastapi import HTTPException
from pwdlib.exceptions import UnknownHashError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.passwords import password_hash
from app.models import AuthCredential, User
from app.repositories.auth import get_login_account


_dummy_hash = password_hash.hash(secrets.token_urlsafe(32))


async def authenticate_user(db: AsyncSession, email: str, password: str, *, commit: bool = True) -> tuple[User, AuthCredential]:
    account = await get_login_account(db, email)
    credential, user = account if account else (None, None)
    now = datetime.now(timezone.utc)
    if credential and credential.locked_until and credential.locked_until > now:
        raise HTTPException(429, "Demasiados intentos. Intenta de nuevo más tarde.")

    stored_hash = credential.password_hash if credential and credential.password_hash else _dummy_hash
    try:
        valid, updated_hash = await asyncio.to_thread(password_hash.verify_and_update, password, stored_hash)
    except (UnknownHashError, ValueError):
        valid, updated_hash = False, None

    if not valid or not credential or not credential.password_hash:
        await _record_failed_attempt(db, credential, now)
        raise HTTPException(401, "Correo o contraseña incorrectos.")

    check_account_access(credential, now)
    credential.failed_attempts = 0
    credential.locked_until = None
    if updated_hash:
        credential.password_hash = updated_hash
    if commit:
        await db.commit()
    return user, credential


async def _record_failed_attempt(db: AsyncSession, credential: AuthCredential | None, now: datetime):
    if credential is None:
        return
    if credential.locked_until and credential.locked_until <= now:
        credential.failed_attempts = 0
        credential.locked_until = None
    credential.failed_attempts += 1
    if credential.failed_attempts >= settings.AUTH_MAX_LOGIN_ATTEMPTS:
        credential.locked_until = now + timedelta(seconds=settings.AUTH_LOGIN_LOCK_SECONDS)
    await db.commit()


def check_account_access(credential: AuthCredential, now: datetime):
    if credential.banned_until and credential.banned_until > now:
        raise HTTPException(403, "Esta cuenta no puede iniciar sesión.")
    if not credential.email_confirmed:
        raise HTTPException(403, "Confirma tu correo antes de iniciar sesión.")
