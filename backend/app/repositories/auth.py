from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuthCredential, User


async def get_login_account(db: AsyncSession, email: str) -> tuple[AuthCredential, User] | None:
    result = await db.execute(
        select(AuthCredential, User)
        .join(User, User.id == AuthCredential.user_id)
        .where(func.lower(User.email) == email.lower())
        .with_for_update(of=AuthCredential)
    )
    return result.one_or_none()
