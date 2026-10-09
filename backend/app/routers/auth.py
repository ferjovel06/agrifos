from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.tokens import create_access_token
from app.db.session import get_db
from app.schemas.auth import LoginRequest, LoginResponse
from app.services.auth import authenticate_user


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    if settings.AUTH_PROVIDER != "native":
        raise HTTPException(503, "El acceso mediante FastAPI aún no está habilitado.")
    user = await authenticate_user(db, str(payload.email), payload.password.get_secret_value())
    response.headers["Cache-Control"] = "no-store"
    return LoginResponse(access_token=create_access_token(user), expires_in=settings.AUTH_ACCESS_TOKEN_SECONDS)
