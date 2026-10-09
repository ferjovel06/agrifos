"""Add owner-scoped change journal, operation receipts and shared weather cache.

Revision ID: 0f11a2b3c4d5
Revises: b2c4d6e8f901
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0f11a2b3c4d5"
down_revision = "b2c4d6e8f901"
branch_labels = depends_on = None
TRACKED = ("farms", "parcels", "readings", "lab_analyses", "parcel_phenological_stages")


def upgrade():
    for table in TRACKED[:4]:
        op.add_column(table, sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
    op.create_table("sync_changes",
        sa.Column("sequence", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", pg.UUID(), nullable=False),
        sa.Column("farm_id", pg.UUID(), nullable=False),
        sa.Column("entity", sa.String(40), nullable=False),
        sa.Column("entity_id", pg.UUID(), nullable=False),
        sa.Column("operation", sa.String(10), nullable=False),
        sa.Column("data", pg.JSONB(), nullable=False))
    op.create_index("ix_sync_changes_user_id", "sync_changes", ["user_id"])
    op.create_table("sync_receipts",
        sa.Column("user_id", pg.UUID(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("operation_id", pg.UUID(), primary_key=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response", pg.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table("sync_cursors",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("user_id", pg.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("after_sequence", sa.BigInteger(), nullable=False),
        sa.Column("until_sequence", sa.BigInteger(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_sync_cursors_user_id", "sync_cursors", ["user_id"])
    op.create_table("weather_http_cache",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("payload", pg.JSONB(), nullable=True),
        sa.Column("last_modified", sa.String(100), nullable=True),
        *[sa.Column(name, sa.DateTime(timezone=True), nullable=True) for name in
          ("fetched_at", "validated_at", "fresh_until", "retry_at")],
        sa.Column("failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(40), nullable=True))
    # Serialize tracked transactions BEFORE taking row locks. Sequence allocation
    # now follows commit order: a high-water cursor cannot skip a late commit.
    # This modest foundation favors correctness over maximum write throughput.
    op.execute("""
        CREATE FUNCTION public.sync_serialize() RETURNS trigger AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(73190641012001);
            RETURN NULL;
        END; $$ LANGUAGE plpgsql;
        CREATE FUNCTION public.sync_revision() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN NEW.revision := 1;
            ELSE NEW.revision := OLD.revision + 1; END IF;
            RETURN NEW;
        END; $$ LANGUAGE plpgsql;
        CREATE FUNCTION public.sync_journal() RETURNS trigger AS $$
        DECLARE item jsonb; owner_id uuid; parent_farm uuid; kind text;
        BEGIN
            item := CASE WHEN TG_OP = 'DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
            kind := CASE WHEN TG_OP = 'DELETE' THEN 'delete' ELSE 'upsert' END;
            IF TG_TABLE_NAME = 'farms' THEN
                parent_farm := (item->>'id')::uuid;
                owner_id := (item->>'user_id')::uuid;
                IF TG_OP = 'UPDATE' AND NEW.user_id <> OLD.user_id THEN
                    INSERT INTO public.sync_changes(user_id,farm_id,entity,entity_id,operation,data)
                    VALUES (OLD.user_id, OLD.id, 'farms', OLD.id, 'delete', '{}'::jsonb);
                END IF;
            ELSE
                IF TG_TABLE_NAME = 'parcels' THEN parent_farm := (item->>'farm_id')::uuid;
                ELSE SELECT farm_id INTO parent_farm FROM public.parcels WHERE id=(item->>'parcel_id')::uuid;
                END IF;
                SELECT user_id INTO owner_id FROM public.farms WHERE id=parent_farm;
                IF TG_TABLE_NAME = 'parcel_phenological_stages' AND kind <> 'delete' THEN
                    SELECT item || jsonb_build_object('name',t.name,'stage_order',t.stage_order,
                        'duration_days',t.duration_days) INTO item
                    FROM public.phenological_stage_templates t WHERE t.id=(item->>'template_id')::uuid;
                END IF;
            END IF;
            IF owner_id IS NOT NULL THEN
                INSERT INTO public.sync_changes(user_id,farm_id,entity,entity_id,operation,data)
                VALUES(owner_id,parent_farm,TG_TABLE_NAME,(item->>'id')::uuid,kind,
                       CASE WHEN kind='delete' THEN '{}'::jsonb ELSE item END);
            END IF;
            IF TG_TABLE_NAME = 'farms' AND TG_OP = 'UPDATE' THEN
                IF NEW.user_id <> OLD.user_id THEN
                    INSERT INTO public.sync_changes(user_id,farm_id,entity,entity_id,operation,data)
                    SELECT NEW.user_id,NEW.id,'parcels',p.id,'upsert',to_jsonb(p)
                    FROM public.parcels p WHERE p.farm_id=NEW.id;
                    INSERT INTO public.sync_changes(user_id,farm_id,entity,entity_id,operation,data)
                    SELECT NEW.user_id,NEW.id,'readings',r.id,'upsert',to_jsonb(r)
                    FROM public.readings r JOIN public.parcels p ON p.id=r.parcel_id WHERE p.farm_id=NEW.id;
                    INSERT INTO public.sync_changes(user_id,farm_id,entity,entity_id,operation,data)
                    SELECT NEW.user_id,NEW.id,'lab_analyses',r.id,'upsert',to_jsonb(r)
                    FROM public.lab_analyses r JOIN public.parcels p ON p.id=r.parcel_id WHERE p.farm_id=NEW.id;
                    INSERT INTO public.sync_changes(user_id,farm_id,entity,entity_id,operation,data)
                    SELECT NEW.user_id,NEW.id,'parcel_phenological_stages',r.id,'upsert',
                        to_jsonb(r)||jsonb_build_object('name',t.name,'stage_order',t.stage_order,'duration_days',t.duration_days)
                    FROM public.parcel_phenological_stages r JOIN public.parcels p ON p.id=r.parcel_id
                    JOIN public.phenological_stage_templates t ON t.id=r.template_id WHERE p.farm_id=NEW.id;
                END IF;
            END IF;
            RETURN NULL;
        END; $$ LANGUAGE plpgsql;
    """)
    for table in TRACKED:
        op.execute(f"CREATE TRIGGER sync_serialize BEFORE INSERT OR UPDATE OR DELETE ON public.{table} FOR EACH STATEMENT EXECUTE FUNCTION public.sync_serialize()")
        if table in TRACKED[:4]:
            op.execute(f"CREATE TRIGGER sync_revision BEFORE INSERT OR UPDATE ON public.{table} FOR EACH ROW EXECUTE FUNCTION public.sync_revision()")
        op.execute(f"CREATE TRIGGER sync_journal AFTER INSERT OR UPDATE OR DELETE ON public.{table} FOR EACH ROW EXECUTE FUNCTION public.sync_journal()")
        # Seed the journal without updating domain timestamps or versions.
        if table == "farms":
            source = "SELECT f.user_id,f.id,'farms',f.id,'upsert',to_jsonb(f) FROM public.farms f"
        elif table == "parcels":
            source = "SELECT f.user_id,f.id,'parcels',p.id,'upsert',to_jsonb(p) FROM public.parcels p JOIN public.farms f ON f.id=p.farm_id"
        elif table == "parcel_phenological_stages":
            source = "SELECT f.user_id,f.id,'parcel_phenological_stages',r.id,'upsert',to_jsonb(r)||jsonb_build_object('name',t.name,'stage_order',t.stage_order,'duration_days',t.duration_days) FROM public.parcel_phenological_stages r JOIN public.parcels p ON p.id=r.parcel_id JOIN public.farms f ON f.id=p.farm_id JOIN public.phenological_stage_templates t ON t.id=r.template_id"
        else:
            source = f"SELECT f.user_id,f.id,'{table}',r.id,'upsert',to_jsonb(r) FROM public.{table} r JOIN public.parcels p ON p.id=r.parcel_id JOIN public.farms f ON f.id=p.farm_id"
        op.execute("INSERT INTO public.sync_changes(user_id,farm_id,entity,entity_id,operation,data) " + source)
    # These tables contain private operations. Mobile clients access only the
    # existing FastAPI authorization boundary, never PostgREST directly.
    for table in ("sync_changes", "sync_receipts", "sync_cursors", "weather_http_cache"):
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON public.{table} FROM PUBLIC")


def downgrade():
    for table in TRACKED:
        for trigger in ("sync_serialize", "sync_journal"):
            op.execute(f"DROP TRIGGER {trigger} ON public.{table}")
        if table in TRACKED[:4]:
            op.execute(f"DROP TRIGGER sync_revision ON public.{table}")
            op.drop_column(table, "revision")
    for function in ("sync_journal", "sync_revision", "sync_serialize"):
        op.execute(f"DROP FUNCTION public.{function}()")
    for table in ("weather_http_cache", "sync_cursors", "sync_receipts", "sync_changes"):
        op.drop_table(table)
