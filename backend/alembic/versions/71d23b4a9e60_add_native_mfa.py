"""Preserve verified TOTP factors with encrypted native storage."""

import base64

from alembic import op
from cryptography.fernet import Fernet
import sqlalchemy as sa

from app.core.config import settings


revision = "71d23b4a9e60"
down_revision = "9a2d81c6f430"
branch_labels = None
depends_on = None


def upgrade():
    cipher = Fernet(settings.AUTH_MFA_ENCRYPTION_KEY.get_secret_value().encode())
    op.add_column("auth_credentials", sa.Column("mfa_failed_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("auth_credentials", sa.Column("mfa_locked_until", sa.DateTime(timezone=True)))
    op.create_table(
        "auth_mfa_factors",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("auth_credentials.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("secret_ciphertext", sa.String(), nullable=False),
        sa.Column("last_verified_counter", sa.BigInteger(), nullable=True),
    )
    op.create_index("ix_auth_mfa_factors_user_id", "auth_mfa_factors", ["user_id"])
    op.create_table(
        "auth_mfa_challenges",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("auth_credentials.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("factor_id", sa.UUID(), sa.ForeignKey("auth_mfa_factors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("password_fingerprint", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_auth_mfa_challenges_user_id", "auth_mfa_challenges", ["user_id"])
    connection = op.get_bind()
    factors = connection.execute(sa.text("""
        SELECT f.id, f.user_id, f.secret, f.last_challenged_at
        FROM auth.mfa_factors f JOIN public.auth_credentials c ON c.user_id=f.user_id
        WHERE f.status='verified' AND f.factor_type='totp'
    """)).mappings().all()
    for factor in factors:
        try:
            if not factor["secret"]:
                raise ValueError("Empty TOTP secret.")
            base64.b32decode(factor["secret"], casefold=False)
        except (ValueError, TypeError) as error:
            raise RuntimeError("An imported TOTP secret requires explicit migration support.") from error
        previous = factor["last_challenged_at"]
        connection.execute(sa.text("""
            INSERT INTO public.auth_mfa_factors (id,user_id,secret_ciphertext,last_verified_counter)
            VALUES (:id,:user_id,:ciphertext,:counter)
        """), {
            "id": factor["id"], "user_id": factor["user_id"],
            "ciphertext": cipher.encrypt(factor["secret"].encode()).decode(),
            "counter": int(previous.timestamp() // 30) if previous else None,
        })


def downgrade():
    op.drop_table("auth_mfa_challenges")
    op.drop_table("auth_mfa_factors")
    op.drop_column("auth_credentials", "mfa_locked_until")
    op.drop_column("auth_credentials", "mfa_failed_attempts")
