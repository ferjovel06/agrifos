import asyncio
from email.message import EmailMessage
import smtplib
import ssl
from typing import Protocol
from urllib.parse import urlencode, urlsplit, urlunsplit

from fastapi import HTTPException

from app.core.config import settings


class AuthMailer(Protocol):
    async def send(self, recipient: str, purpose: str, token: str) -> None: ...


class SmtpAuthMailer:
    async def send(self, recipient: str, purpose: str, token: str) -> None:
        try:
            await asyncio.to_thread(self._send, recipient, purpose, token)
        except (OSError, smtplib.SMTPException) as error:
            raise HTTPException(503, "No se pudo enviar el correo. Intenta de nuevo más tarde.") from error

    def _send(self, recipient: str, purpose: str, token: str):
        redirect = urlsplit(settings.AUTH_EMAIL_REDIRECT_URL)
        link = urlunsplit((redirect.scheme, redirect.netloc, redirect.path,
                          urlencode({"type": purpose, "token": token}), ""))
        message = EmailMessage()
        message["From"] = settings.SMTP_FROM
        message["To"] = recipient
        message["Subject"] = "Confirma tu correo en Agrifos" if purpose == "confirmation" else "Recupera tu acceso a Agrifos"
        message.set_content(f"Abre este enlace para continuar en Agrifos:\n{link}\n\n"
                            "El enlace vence y solo puede usarse una vez. Si no lo solicitaste, ignora este correo.")
        context = ssl.create_default_context()
        transport = smtplib.SMTP_SSL if settings.SMTP_SECURITY == "ssl" else smtplib.SMTP
        options = {"context": context} if settings.SMTP_SECURITY == "ssl" else {}
        with transport(settings.SMTP_HOST, settings.SMTP_PORT,
                       timeout=settings.SMTP_TIMEOUT_SECONDS, **options) as smtp:
            if settings.SMTP_SECURITY == "starttls":
                smtp.starttls(context=context)
            if settings.SMTP_USERNAME:
                smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD.get_secret_value())
            smtp.send_message(message)


def get_auth_mailer() -> AuthMailer:
    if not settings.SMTP_HOST or not settings.SMTP_FROM or not settings.AUTH_EMAIL_REDIRECT_URL:
        raise HTTPException(503, "El servicio de correo todavía no está configurado.")
    return SmtpAuthMailer()
