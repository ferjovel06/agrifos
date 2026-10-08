"""Read-only PostgreSQL comparison; verify real application drift stays visible."""
import os

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Column, MetaData, String, create_engine
from integration import validate_local_targets

import app.models  # Load the application's complete metadata.
from app.core.config import settings
from app.db.base import Base
from app.db.migration_scope import include_application_object


def main():
    validate_local_targets(os.environ)
    engine = create_engine(settings.DATABASE_URL.replace("+asyncpg", "+psycopg2"))
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            context = MigrationContext.configure(connection, opts={
                "compare_type": True, "include_object": include_application_object,
            })
            assert not compare_metadata(context, Base.metadata), "Application metadata differs"
            for probe in ("column", "index", "foreign_key"):
                metadata = MetaData()
                for table in Base.metadata.sorted_tables:
                    table.to_metadata(metadata)
                if probe == "column":
                    metadata.tables["users"].append_column(Column("_agrifos_drift_probe", String()))
                    expected = "add_column"
                elif probe == "index":
                    table = metadata.tables["agronomic_reference_sets"]
                    table.indexes.remove(next(iter(table.indexes)))
                    expected = "remove_index"
                else:
                    fk, = metadata.tables["stage_factors"].c.stage_id.foreign_keys
                    fk.ondelete = fk.constraint.ondelete = None
                    expected = "remove_fk"
                differences = compare_metadata(context, metadata)
                assert any(item[0] == expected for item in differences), f"Hidden {probe} drift"
            print("PASS: read-only real PostgreSQL comparison; application column/index/FK drift remains detectable.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
