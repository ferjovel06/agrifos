"""Regressions for differences observed against real PostgreSQL migrations."""
import unittest

from sqlalchemy import Column, MetaData, String, Table
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from app.db.migration_scope import include_application_object
from app.models.agronomic_reference import AgronomicReferenceSet
from app.models.fertilization_engine import OptimalRequirement, StageFactor
from app.models.user import User, auth_users


class MigrationMetadataTests(unittest.TestCase):
    def test_only_supabase_reference_table_is_excluded(self):
        for reflected in (False, True):
            self.assertFalse(include_application_object(
                auth_users, "users", "table", reflected, None))
            self.assertTrue(include_application_object(
                User.__table__, "users", "table", reflected, None))
        other_auth_table = Table("application_owned", MetaData(), schema="auth")
        self.assertTrue(include_application_object(
            other_auth_table, "application_owned", "table", False, None))
        column = Column("new_application_column", String())
        self.assertTrue(include_application_object(
            column, column.name, "column", False, None))
        fk = next(iter(User.__table__.c.id.foreign_keys)).constraint
        self.assertTrue(include_application_object(
            fk, fk.name, "foreign_key_constraint", False, None))

    def test_active_reference_index_preserves_partial_unique_policy(self):
        index, = AgronomicReferenceSet.__table__.indexes
        ddl = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
        self.assertEqual(ddl, "CREATE UNIQUE INDEX ix_agronomic_reference_sets_active "
                         "ON agronomic_reference_sets (key) WHERE is_active")

    def test_stage_foreign_keys_preserve_existing_delete_restrictions(self):
        for model, name in (
            (OptimalRequirement, "fk_optimal_requirement_stage_template"),
            (StageFactor, "fk_stage_factor_stage_template"),
        ):
            with self.subTest(model=model.__name__):
                fk, = model.__table__.c.stage_id.foreign_keys
                self.assertEqual(fk.ondelete, "RESTRICT")
                self.assertEqual(fk.constraint.name, name)
                self.assertEqual(fk.target_fullname, "phenological_stage_templates.id")
