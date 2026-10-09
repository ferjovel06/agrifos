"""Import native login credentials without changing existing accounts."""

from alembic import op
import sqlalchemy as sa


revision = "9a2d81c6f430"
down_revision = "b2c4d6e8f901"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "auth_credentials",
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("password_hash", sa.String(), nullable=True),
        sa.Column("email_confirmed", sa.Boolean(), nullable=False),
        sa.Column("mfa_enabled", sa.Boolean(), nullable=False),
        sa.Column("banned_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("""
        INSERT INTO public.auth_credentials
            (user_id, password_hash, email_confirmed, mfa_enabled, banned_until)
        SELECT u.id, nullif(u.encrypted_password, ''), u.email_confirmed_at IS NOT NULL,
            EXISTS (SELECT 1 FROM auth.mfa_factors f WHERE f.user_id=u.id AND f.status='verified'),
            u.banned_until
        FROM auth.users u JOIN public.users p ON p.id=u.id
        WHERE u.deleted_at IS NULL
    """)


def downgrade():
    op.drop_table("auth_credentials")
