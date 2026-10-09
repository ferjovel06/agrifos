from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from typing import Literal

import jwt

from app.core.config import settings
from app.models import User


def create_access_token(user: User, *, aal: Literal["aal1", "aal2"] = "aal1") -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user.id),
            "email": user.email,
            "iat": now.timestamp(),
            "exp": (now + timedelta(seconds=settings.AUTH_ACCESS_TOKEN_SECONDS)).timestamp(),
            "iss": settings.AUTH_JWT_ISSUER,
            "aud": settings.AUTH_JWT_AUDIENCE,
            "jti": str(uuid4()),
            "aal": aal,
            "type": "access",
        },
        settings.AUTH_JWT_SECRET.get_secret_value(),
        algorithm="HS256",
    )


def verify_access_token(token: str) -> dict:
    claims = jwt.decode(
        token,
        settings.AUTH_JWT_SECRET.get_secret_value(),
        algorithms=["HS256"],
        audience=settings.AUTH_JWT_AUDIENCE,
        issuer=settings.AUTH_JWT_ISSUER,
        options={"require": ["sub", "email", "iat", "exp", "iss", "aud", "jti", "aal", "type"]},
    )
    if claims["type"] != "access" or claims["aal"] not in ("aal1", "aal2"):
        raise jwt.InvalidTokenError("Invalid access token purpose or authentication level.")
    if not isinstance(claims["email"], str) or not claims["email"]:
        raise jwt.InvalidTokenError("Invalid token identity.")
    try:
        UUID(claims["sub"])
        UUID(claims["jti"])
    except (ValueError, TypeError, AttributeError) as error:
        raise jwt.InvalidTokenError("Invalid token identity.") from error
    return claims
