import asyncio
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import secrets
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.passwords import password_hash
from app.models import AuthCredential, AuthEmailToken, User
from app.repositories.auth import get_login_account
from app.repositories.auth_management import get_account, get_email_proof, latest_email_proof
from app.services.auth import authenticate_user, check_account_access
from app.services.auth_mail import AuthMailer
from app.services.mfa import password_fingerprint


def validate_new_password(password: str):
    if len(password) < settings.AUTH_PASSWORD_MIN_LENGTH:
        raise HTTPException(422, f"La contraseña debe tener al menos {settings.AUTH_PASSWORD_MIN_LENGTH} caracteres.")


async def register_account(db: AsyncSession, name: str, email: str, password: str, mailer: AuthMailer):
    validate_new_password(password)
    if len(name.strip()) < 2:
        raise HTTPException(422, "El nombre debe tener al menos dos caracteres.")
    email = email.lower()
    account = await get_login_account(db, email)
    if account:
        return
    user = User(id=uuid4(), name=name.strip(), email=email, role="farmer")
    credential = AuthCredential(user_id=user.id,
        password_hash=await asyncio.to_thread(password_hash.hash, password),
        email_confirmed=False, mfa_enabled=False)
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        return
    db.add(credential)
    await db.flush()
    await send_account_email(db, credential, user, "confirmation", mailer)


async def request_account_email(db: AsyncSession, email: str, purpose: str, mailer: AuthMailer):
    account = await get_login_account(db, email)
    if account is None:
        return
    credential, user = account
    now = datetime.now(timezone.utc)
    if credential.banned_until and credential.banned_until > now:
        return
    if purpose == "confirmation" and credential.email_confirmed:
        return
    if purpose == "recovery" and not credential.email_confirmed:
        return
    await send_account_email(db, credential, user, purpose, mailer)


async def send_account_email(db: AsyncSession, credential: AuthCredential, user: User,
                             purpose: str, mailer: AuthMailer):
    now = datetime.now(timezone.utc)
    previous = await latest_email_proof(db, user.id, purpose)
    if previous and (now - previous.created_at).total_seconds() < settings.AUTH_EMAIL_COOLDOWN_SECONDS:
        return
    token = secrets.token_urlsafe(32)
    proof = AuthEmailToken(digest=sha256(token.encode()).hexdigest(), user_id=user.id,
        purpose=purpose, password_fingerprint=password_fingerprint(credential.password_hash or ""),
        created_at=now, expires_at=now + timedelta(seconds=settings.AUTH_EMAIL_TOKEN_SECONDS))
    if previous:
        previous.consumed_at = now
    db.add(proof)
    await db.flush()
    try:
        await mailer.send(user.email, purpose, token)
        await db.commit()
    except Exception:
        await db.rollback()
        raise


async def redeem_email(db: AsyncSession, token: str, purpose: str, new_password: str | None = None):
    if new_password is not None:
        validate_new_password(new_password)
    account = await get_email_proof(db, sha256(token.encode()).hexdigest(), purpose)
    now = datetime.now(timezone.utc)
    if account is None:
        raise _invalid_link()
    proof, credential, user = account
    if proof.consumed_at or proof.expires_at <= now:
        raise _invalid_link()
    if proof.password_fingerprint != password_fingerprint(credential.password_hash or ""):
        raise _invalid_link()
    if credential.banned_until and credential.banned_until > now:
        raise _invalid_link()
    if purpose == "confirmation":
        credential.email_confirmed = True
    else:
        check_account_access(credential, now)
        credential.password_hash = await asyncio.to_thread(password_hash.hash, new_password)
        _reset_password_state(credential, now)
    proof.consumed_at = now
    await db.commit()


async def change_password(db: AsyncSession, user_id: UUID, current_password: str, new_password: str):
    validate_new_password(new_password)
    account = await get_account(db, user_id)
    if account is None:
        raise HTTPException(401, "Tu sesión venció. Inicia sesión de nuevo.")
    credential, user = account
    # Reuse login validation and its persistent brute-force counter.
    await authenticate_user(db, user.email, current_password, commit=False)
    if current_password == new_password:
        raise HTTPException(422, "La nueva contraseña debe ser diferente de la anterior.")
    credential.password_hash = await asyncio.to_thread(password_hash.hash, new_password)
    _reset_password_state(credential, datetime.now(timezone.utc))
    await db.commit()


def _reset_password_state(credential: AuthCredential, now: datetime):
    credential.tokens_valid_after = now
    credential.failed_attempts = 0
    credential.locked_until = None


def _invalid_link():
    return HTTPException(401, "El enlace venció o ya fue utilizado. Solicita uno nuevo.")
