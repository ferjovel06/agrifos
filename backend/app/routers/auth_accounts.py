from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, get_verified_claims
from app.core.config import settings
from app.core.tokens import create_access_token
from app.db.session import get_db
from app.models import User
from app.routers.auth import require_native_auth
from app.schemas.auth import (
    EmailRequest, EmailTokenRequest, LoginResponse, MfaEnrollmentResponse,
    MfaEnrollmentVerifyRequest, PasswordChangeRequest, PasswordResetRequest, RegisterRequest,
)
from app.services import auth_accounts, mfa_management
from app.services.auth_mail import AuthMailer, get_auth_mailer


def prevent_auth_cache(response: Response):
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(require_native_auth), Depends(prevent_auth_cache)])
EMAIL_RESPONSE = {"message": "Si corresponde a tu cuenta, recibirás un correo para continuar."}


@router.post("/register", status_code=202)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db), mailer: AuthMailer = Depends(get_auth_mailer)):
    await auth_accounts.register_account(db, payload.name, str(payload.email), payload.password.get_secret_value(), mailer)
    return EMAIL_RESPONSE


@router.post("/email/resend", status_code=202)
async def resend_confirmation(payload: EmailRequest, db: AsyncSession = Depends(get_db), mailer: AuthMailer = Depends(get_auth_mailer)):
    await auth_accounts.request_account_email(db, str(payload.email), "confirmation", mailer)
    return EMAIL_RESPONSE


@router.post("/email/confirm", status_code=204)
async def confirm_email(payload: EmailTokenRequest, db: AsyncSession = Depends(get_db)):
    await auth_accounts.redeem_email(db, payload.token.get_secret_value(), "confirmation")


@router.post("/password/forgot", status_code=202)
async def forgot_password(payload: EmailRequest, db: AsyncSession = Depends(get_db), mailer: AuthMailer = Depends(get_auth_mailer)):
    await auth_accounts.request_account_email(db, str(payload.email), "recovery", mailer)
    return EMAIL_RESPONSE


@router.post("/password/reset", status_code=204)
async def reset_password(payload: PasswordResetRequest, db: AsyncSession = Depends(get_db)):
    await auth_accounts.redeem_email(db, payload.token.get_secret_value(), "recovery", payload.new_password.get_secret_value())


@router.post("/password/change", status_code=204)
async def change_password(payload: PasswordChangeRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await auth_accounts.change_password(db, user.id, payload.current_password.get_secret_value(), payload.new_password.get_secret_value())


@router.get("/mfa/status")
async def mfa_status(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return {"enabled": await mfa_management.mfa_status(db, user.id)}


@router.post("/mfa/enroll", response_model=MfaEnrollmentResponse)
async def enroll_mfa(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await mfa_management.enroll_mfa(db, user.id)


def _session(user: User, aal: str) -> LoginResponse:
    return LoginResponse(access_token=create_access_token(user, aal=aal), expires_in=settings.AUTH_ACCESS_TOKEN_SECONDS)


@router.post("/mfa/enroll/confirm", response_model=LoginResponse)
async def confirm_mfa(payload: MfaEnrollmentVerifyRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    user = await mfa_management.confirm_mfa(db, user.id, payload.factor_id, payload.code)
    return _session(user, "aal2")


@router.delete("/mfa/enroll/{factor_id}", status_code=204)
async def cancel_mfa(factor_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await mfa_management.cancel_mfa(db, user.id, factor_id)


@router.post("/mfa/disable", response_model=LoginResponse)
async def disable_mfa(user: User = Depends(get_current_user), claims: dict = Depends(get_verified_claims), db: AsyncSession = Depends(get_db)):
    if claims["aal"] != "aal2":
        raise HTTPException(403, "Verifica el segundo factor antes de desactivarlo.")
    user = await mfa_management.disable_mfa(db, user.id)
    return _session(user, "aal1")
