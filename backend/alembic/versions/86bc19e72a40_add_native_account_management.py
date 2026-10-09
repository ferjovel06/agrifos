"""Allow native users and add expiring account-management proofs."""

from alembic import op
import sqlalchemy as sa

revision = "86bc19e72a40"
down_revision = "71d23b4a9e60"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    for constraint in sa.inspect(connection).get_foreign_keys("users", schema="public"):
        if constraint["referred_schema"] == "auth" and constraint["referred_table"] == "users":
            op.drop_constraint(constraint["name"], "users", type_="foreignkey", schema="public")
    op.create_index("uq_users_email_lower", "users", [sa.text("lower(email)")], unique=True)
    op.add_column("auth_credentials", sa.Column("tokens_valid_after", sa.DateTime(timezone=True)))
    op.add_column("auth_mfa_factors", sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.alter_column("auth_mfa_factors", "verified", server_default=sa.false())
    op.add_column("auth_mfa_factors", sa.Column("enrollment_expires_at", sa.DateTime(timezone=True)))
    op.create_table(
        "auth_email_tokens",
        sa.Column("digest", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("auth_credentials.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("purpose", sa.String(20), nullable=False),
        sa.Column("password_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_auth_email_tokens_user_id", "auth_email_tokens", ["user_id"])


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT EXISTS (SELECT 1 FROM public.users u LEFT JOIN auth.users a ON a.id=u.id WHERE a.id IS NULL)")).scalar():
        raise RuntimeError("Native accounts must be migrated before restoring the Supabase foreign key.")
    op.drop_table("auth_email_tokens")
    op.drop_column("auth_mfa_factors", "enrollment_expires_at")
    op.drop_column("auth_mfa_factors", "verified")
    op.drop_column("auth_credentials", "tokens_valid_after")
    op.drop_index("uq_users_email_lower", table_name="users")
    op.create_foreign_key("users_id_fkey", "users", "users", ["id"], ["id"], source_schema="public", referent_schema="auth", ondelete="CASCADE")
