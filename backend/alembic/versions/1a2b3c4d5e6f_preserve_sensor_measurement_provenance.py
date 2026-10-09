"""Preserve sensor originals, versioned processing and paired calibration data.

Revision ID: 1a2b3c4d5e6f
Revises: 0f11a2b3c4d5
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "1a2b3c4d5e6f"
down_revision = "0f11a2b3c4d5"
branch_labels = depends_on = None
VARIABLES = ("nitrogen", "phosphorus", "potassium", "ec", "ph", "temperature", "humidity")


def upgrade():
    for name in VARIABLES:
        op.alter_column("readings", name, existing_type=sa.Float(), nullable=True)
    op.add_column("readings", sa.Column("measurement", pg.JSONB(), nullable=True))
    op.add_column("readings", sa.Column("derived_results", pg.JSONB(), nullable=False, server_default="[]"))
    op.add_column("readings", sa.Column("received_at", sa.DateTime(timezone=True), nullable=True))
    op.alter_column("readings", "received_at", server_default=sa.func.now())
    op.create_check_constraint("ck_readings_provenance_or_legacy_values", "readings",
        "measurement IS NOT NULL OR (" + " AND ".join(f"{name} IS NOT NULL" for name in VARIABLES) + ")")
    op.create_check_constraint("ck_readings_measurement_version", "readings",
        "measurement IS NULL OR (jsonb_typeof(measurement)='object' AND COALESCE(measurement->'contract_version'='1'::jsonb,false))")
    op.create_table("sensor_calibration_pairs",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("user_id", pg.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reading_id", pg.UUID(), sa.ForeignKey("readings.id"), nullable=False),
        sa.Column("sample_id", sa.String(120), nullable=False),
        sa.Column("context_key", sa.String(64), nullable=True),
        sa.Column("variable", sa.String(32), nullable=False),
        sa.Column("laboratory", pg.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "reading_id", "variable", name="uq_sensor_calibration_pair"))
    op.create_table("sensor_calibrations",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("user_id", pg.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("profile_id", sa.String(120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False, server_default="candidate"),
        sa.Column("profile", pg.JSONB(), nullable=False),
        sa.Column("pair_ids", pg.JSONB(), nullable=False),
        sa.Column("validation", pg.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "profile_id", "version", name="uq_sensor_calibration_version"),
        sa.CheckConstraint("state IN ('candidate', 'validated', 'retired')", name="ck_sensor_calibration_state"))
    op.create_table("reading_results",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("reading_id", pg.UUID(), sa.ForeignKey("readings.id"), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("algorithm_version", sa.String(80), nullable=False),
        sa.Column("calibration_id", pg.UUID(), sa.ForeignKey("sensor_calibrations.id"), nullable=True),
        sa.Column("payload", pg.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("reading_id", "fingerprint", name="uq_reading_results_fingerprint"))
    for table, column in (("sensor_calibration_pairs", "user_id"), ("sensor_calibrations", "user_id"), ("reading_results", "reading_id")):
        op.create_index(f"ix_{table}_{column}", table, [column])
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON public.{table} FROM PUBLIC")
        # Supabase installations may grant new tables through default privileges.
        # Revoke those direct client grants without requiring fixture auth roles.
        for role in ("anon", "authenticated"):
            op.execute(f"""DO $$ BEGIN
                IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN
                    EXECUTE 'REVOKE ALL ON public.{table} FROM {role}';
                END IF;
                END $$""")
    op.create_index("ix_sensor_calibration_pairs_context_key", "sensor_calibration_pairs", ["context_key"])
    op.execute("""
        CREATE FUNCTION public.sensor_original_immutable() RETURNS trigger AS $$
        BEGIN
            IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Sensor measurements are immutable'; END IF;
            IF (to_jsonb(NEW) - 'revision' - 'derived_results') IS DISTINCT FROM
               (to_jsonb(OLD) - 'revision' - 'derived_results') THEN
                RAISE EXCEPTION 'Sensor measurements are immutable';
            END IF;
            RETURN NEW;
        END; $$ LANGUAGE plpgsql;
        CREATE TRIGGER sensor_original_immutable BEFORE UPDATE OR DELETE ON public.readings
            FOR EACH ROW EXECUTE FUNCTION public.sensor_original_immutable();
        CREATE FUNCTION public.sensor_append_only() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'Sensor evidence is append-only'; END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER sensor_pair_immutable BEFORE UPDATE OR DELETE ON public.sensor_calibration_pairs
            FOR EACH ROW EXECUTE FUNCTION public.sensor_append_only();
        CREATE TRIGGER sensor_result_immutable BEFORE UPDATE OR DELETE ON public.reading_results
            FOR EACH ROW EXECUTE FUNCTION public.sensor_append_only();
        CREATE FUNCTION public.sensor_profile_immutable() RETURNS trigger AS $$
        BEGIN
            IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Calibration version history is immutable'; END IF;
            IF (to_jsonb(NEW) - 'state' - 'validation') IS DISTINCT FROM
               (to_jsonb(OLD) - 'state' - 'validation') OR
               (OLD.validation IS NOT NULL AND NEW.validation IS DISTINCT FROM OLD.validation) OR
               NOT (NEW.state=OLD.state OR (OLD.state='candidate' AND NEW.state IN ('validated','retired')) OR
                    (OLD.state='validated' AND NEW.state='retired')) THEN
                RAISE EXCEPTION 'Calibration versions and validation evidence are immutable';
            END IF;
            RETURN NEW;
        END; $$ LANGUAGE plpgsql;
        CREATE TRIGGER sensor_profile_immutable BEFORE UPDATE OR DELETE ON public.sensor_calibrations
            FOR EACH ROW EXECUTE FUNCTION public.sensor_profile_immutable();
        CREATE FUNCTION public.sensor_result_projection() RETURNS trigger AS $$
        BEGIN
            UPDATE public.readings SET derived_results=derived_results ||
                jsonb_build_array(NEW.payload || jsonb_build_object('id',NEW.id,'created_at',NEW.created_at))
                WHERE id=NEW.reading_id;
            RETURN NULL;
        END; $$ LANGUAGE plpgsql;
        CREATE TRIGGER sensor_result_projection AFTER INSERT ON public.reading_results
            FOR EACH ROW EXECUTE FUNCTION public.sensor_result_projection();
    """)


def downgrade():
    # Preserve raw data: downgrade cannot represent partial v1 measurements.
    op.execute("""DO $$ BEGIN
        IF EXISTS(SELECT 1 FROM readings WHERE measurement IS NOT NULL) THEN
            RAISE EXCEPTION 'Export v1 sensor evidence before downgrading';
        END IF;
        END $$""")
    op.execute("DROP TRIGGER sensor_original_immutable ON public.readings")
    op.drop_constraint("ck_readings_measurement_version", "readings", type_="check")
    op.drop_constraint("ck_readings_provenance_or_legacy_values", "readings", type_="check")
    for table in ("reading_results", "sensor_calibrations", "sensor_calibration_pairs"):
        op.drop_table(table)
    for function in ("sensor_result_projection", "sensor_profile_immutable", "sensor_append_only", "sensor_original_immutable"):
        op.execute(f"DROP FUNCTION public.{function}()")
    for name in ("received_at", "derived_results", "measurement"):
        op.drop_column("readings", name)
    for name in VARIABLES:
        op.alter_column("readings", name, existing_type=sa.Float(), nullable=False)
