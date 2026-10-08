import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "integration.py"
PROJECT = "agrifos-it-12ab34cd"
LOCAL_ENVIRONMENT = {
    "LOCAL_TEST_PROJECT": PROJECT,
    "LOCAL_SUPABASE_URL": f"http://supabase_kong_{PROJECT}:8000",
    "API_BASE_URL": "http://api:8000",
    "DATABASE_URL": (
        f"postgresql+asyncpg://postgres:test-only-password"
        f"@supabase_db_{PROJECT}:5432/postgres"
    ),
}


def load_integration(environment):
    spec = importlib.util.spec_from_file_location("agrifos_docker_integration", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(os.environ, environment, clear=True):
        spec.loader.exec_module(module)
    return module


class IntegrationIsolationTests(unittest.TestCase):
    def setUp(self):
        # Guard tests must never perform HTTP or database operations, including import.
        for target in ("httpx.request", "httpx.get", "psycopg2.connect"):
            patcher = patch(target, side_effect=AssertionError("Unexpected network access"))
            mocked = patcher.start()
            self.addCleanup(patcher.stop)
            self.addCleanup(mocked.assert_not_called)
        self.integration = load_integration(LOCAL_ENVIRONMENT)

    def reject(self, **overrides):
        with self.assertRaises(SystemExit):
            self.integration.validate_local_targets({**LOCAL_ENVIRONMENT, **overrides})

    def test_accepts_only_coordinates_of_the_named_isolated_project(self):
        project, auth, api = self.integration.validate_local_targets(LOCAL_ENVIRONMENT)

        self.assertEqual(project, PROJECT)
        self.assertEqual(auth, LOCAL_ENVIRONMENT["LOCAL_SUPABASE_URL"])
        self.assertEqual(api, "http://api:8000")

    def test_rejects_remote_auth_before_administrative_operations(self):
        self.reject(LOCAL_SUPABASE_URL="https://remote.example")

    def test_rejects_remote_application_api(self):
        self.reject(API_BASE_URL="https://api.remote.example")

    def test_rejects_remote_database_even_with_a_valid_test_project_name(self):
        self.reject(
            DATABASE_URL="postgresql+asyncpg://postgres:test-only-password@remote.example:5432/postgres",
        )

    def test_rejects_hosts_that_belong_to_another_isolated_project(self):
        other = "agrifos-it-98dc76ba"
        self.reject(LOCAL_SUPABASE_URL=f"http://supabase_kong_{other}:8000")
        self.reject(
            DATABASE_URL=f"postgresql+asyncpg://postgres:test-only-password@supabase_db_{other}:5432/postgres",
        )

    def test_rejects_normal_development_project_and_malformed_test_identities(self):
        for project in ("agrifos", "agrifos-it-123", "agrifos-it-1234ABCD", "agrifos-it-12345678-extra"):
            with self.subTest(project=project):
                self.reject(LOCAL_TEST_PROJECT=project)

    def test_rejects_different_database_port_schema_or_driver(self):
        for database in (
            f"postgresql+asyncpg://postgres:test-only-password@supabase_db_{PROJECT}:54322/postgres",
            f"postgresql+asyncpg://postgres:test-only-password@supabase_db_{PROJECT}:5432/another_database",
            f"postgresql://postgres:test-only-password@supabase_db_{PROJECT}:5432/postgres",
        ):
            with self.subTest(database=database):
                self.reject(DATABASE_URL=database)

    def test_rejects_database_query_overrides_that_can_redirect_libpq(self):
        for query in ("host=remote.example", "hostaddr=203.0.113.10", "port=15432"):
            with self.subTest(query=query):
                self.reject(DATABASE_URL=f"{LOCAL_ENVIRONMENT['DATABASE_URL']}?{query}")

    def test_rejects_credentials_or_extra_paths_in_http_coordinates(self):
        self.reject(LOCAL_SUPABASE_URL=f"http://user:test-only-password@supabase_kong_{PROJECT}:8000")
        self.reject(API_BASE_URL="http://api:8000/another-service")

    def test_import_refuses_remote_targets_without_reaching_network_code(self):
        with self.assertRaises(SystemExit):
            load_integration({**LOCAL_ENVIRONMENT, "LOCAL_SUPABASE_URL": "https://remote.example"})

    def test_rejects_missing_configuration(self):
        with self.assertRaises(SystemExit):
            self.integration.validate_local_targets({})


if __name__ == "__main__":
    unittest.main()
