from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuthCredential, AuthMfaChallenge, AuthMfaFactor, User


async def get_login_factor(db: AsyncSession, user_id: UUID) -> AuthMfaFactor | None:
    result = await db.execute(
        select(AuthMfaFactor).where(AuthMfaFactor.user_id == user_id, AuthMfaFactor.verified.is_(True))
        .order_by(AuthMfaFactor.id).limit(1)
    )
    return result.scalar_one_or_none()


async def get_challenge_account(db: AsyncSession, challenge_id: UUID):
    result = await db.execute(
        select(AuthMfaChallenge, AuthCredential, AuthMfaFactor, User)
        .join(AuthCredential, AuthCredential.user_id == AuthMfaChallenge.user_id)
        .join(AuthMfaFactor, (AuthMfaFactor.id == AuthMfaChallenge.factor_id) &
              (AuthMfaFactor.user_id == AuthMfaChallenge.user_id))
        .join(User, User.id == AuthCredential.user_id)
        .where(AuthMfaChallenge.id == challenge_id)
        .with_for_update(of=(AuthMfaChallenge, AuthCredential, AuthMfaFactor))
    )
    return result.one_or_none()
