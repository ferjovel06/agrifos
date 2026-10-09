from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.tokens import create_access_token
from app.db.session import get_db
from app.schemas.auth import LoginRequest, LoginResponse, MfaChallengeResponse, MfaVerifyRequest
from app.services.auth import authenticate_user
from app.services.mfa import start_login_challenge, verify_login_challenge


router = APIRouter(prefix="/auth", tags=["auth"])


def require_native_auth():
    if settings.AUTH_PROVIDER != "native":
        raise HTTPException(503, "El acceso mediante FastAPI aún no está habilitado.")


@router.post("/login", response_model=LoginResponse | MfaChallengeResponse, dependencies=[Depends(require_native_auth)])
async def login(payload: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    user, credential = await authenticate_user(db, str(payload.email), payload.password.get_secret_value())
    response.headers["Cache-Control"] = "no-store"
    if credential.mfa_enabled:
        challenge = await start_login_challenge(db, credential)
        return MfaChallengeResponse(challenge_id=challenge.id, expires_in=settings.AUTH_MFA_CHALLENGE_SECONDS)
    return LoginResponse(access_token=create_access_token(user), expires_in=settings.AUTH_ACCESS_TOKEN_SECONDS)


@router.post("/mfa/verify", response_model=LoginResponse, dependencies=[Depends(require_native_auth)])
async def verify_mfa(payload: MfaVerifyRequest, response: Response, db: AsyncSession = Depends(get_db)):
    user = await verify_login_challenge(db, payload.challenge_id, payload.code)
    response.headers["Cache-Control"] = "no-store"
    return LoginResponse(access_token=create_access_token(user, aal="aal2"), expires_in=settings.AUTH_ACCESS_TOKEN_SECONDS)
