from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuthCredential, AuthEmailToken, AuthMfaFactor, User


async def get_account(db: AsyncSession, user_id: UUID, *, lock: bool = True):
    query = select(AuthCredential, User).join(User, User.id == AuthCredential.user_id).where(User.id == user_id)
    if lock:
        query = query.with_for_update(of=AuthCredential)
    return (await db.execute(query)).one_or_none()


async def get_email_proof(db: AsyncSession, digest: str, purpose: str):
    proof = (await db.execute(select(AuthEmailToken).where(
        AuthEmailToken.digest == digest, AuthEmailToken.purpose == purpose))).scalar_one_or_none()
    if proof is None:
        return None
    # Use the same credential-first lock order as email issuance and password changes.
    account = await get_account(db, proof.user_id)
    await db.refresh(proof)
    return (proof, *account) if account else None


async def latest_email_proof(db: AsyncSession, user_id: UUID, purpose: str):
    return (await db.execute(select(AuthEmailToken).where(
        AuthEmailToken.user_id == user_id, AuthEmailToken.purpose == purpose)
        .order_by(AuthEmailToken.created_at.desc()).limit(1))).scalar_one_or_none()


async def get_factor(db: AsyncSession, user_id: UUID, factor_id: UUID):
    return (await db.execute(select(AuthMfaFactor).where(
        AuthMfaFactor.user_id == user_id, AuthMfaFactor.id == factor_id)
        .with_for_update())).scalar_one_or_none()
