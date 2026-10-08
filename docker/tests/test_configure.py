import base64
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "configure.py"
SPEC = importlib.util.spec_from_file_location("agrifos_docker_configure", SCRIPT)
configure = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(configure)


def legacy_key(role):
    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    return (
        f"{encode({'alg': 'HS256', 'typ': 'JWT'})}."
        f"{encode({'role': role})}.test-only-signature"
    )


class LocalConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name)
        self.status = {
            "DB_URL": (
                "postgresql://postgres:test-only-database-password"
                "@127.0.0.1:54322/postgres"
            ),
            "PUBLISHABLE_KEY": "sb_publishable_test_only_public_fixture",
            "SERVICE_ROLE_KEY": "test-only-administrative-server-key",
        }

    def run_configuration(self, status=None, *arguments):
        logged = io.StringIO()
        with (
            patch.object(configure.sys, "argv", [str(SCRIPT), *arguments]),
            patch.object(
                configure.sys,
                "stdin",
                io.StringIO(json.dumps(self.status if status is None else status)),
            ),
            redirect_stdout(logged),
        ):
            configure.main(output=self.output)
        return logged.getvalue()

    def test_generates_local_container_coordinates_without_logging_credentials(self):
        logged = self.run_configuration(
            None,
            "--project", "agrifos-it-12ab34cd",
            "--port", "54331",
            "--api-port", "8010",
            "--integration",
        )
        backend = (self.output / "backend.env").read_text(encoding="utf-8")
        client = (self.output / "client.env").read_text(encoding="utf-8")
        integration = (self.output / "integration.env").read_text(encoding="utf-8")

        self.assertIn("@supabase_db_agrifos-it-12ab34cd:5432/postgres", backend)
        self.assertIn("SUPABASE_URL='http://127.0.0.1:54331'", backend)
        self.assertIn(
            "http://supabase_kong_agrifos-it-12ab34cd:8000/auth/v1/.well-known/jwks.json",
            backend,
        )
        self.assertIn("SUPABASE_URL='http://10.0.2.2:54331'", client)
        self.assertIn("API_BASE_URL='http://10.0.2.2:8010'", client)
        self.assertNotIn("SERVICE_ROLE", client)
        self.assertNotIn("DATABASE_URL", client)
        self.assertIn("LOCAL_TEST_PROJECT='agrifos-it-12ab34cd'", integration)
        for sensitive in (
            "test-only-database-password",
            self.status["DB_URL"],
            self.status["PUBLISHABLE_KEY"],
            self.status["SERVICE_ROLE_KEY"],
        ):
            self.assertNotIn(sensitive, logged)
        for path in self.output.iterdir():
            self.assertNotIn(b"\r", path.read_bytes())
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_repeated_configuration_preserves_customized_files_and_permissions(self):
        self.run_configuration(None, "--integration")
        paths = [self.output / name for name in (
            "backend.env", "client.env", "integration.env",
        )]
        for path in paths:
            with path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write("# Local customization must survive reconfiguration.\n")
        previous = {path.name: path.read_bytes() for path in paths}
        modes = {path.name: stat.S_IMODE(path.stat().st_mode) for path in paths}
        different_status = {
            **self.status,
            "PUBLISHABLE_KEY": "sb_publishable_different_test_only_fixture",
            "SERVICE_ROLE_KEY": "different-test-only-server-key",
        }

        logged = self.run_configuration(different_status, "--integration")

        self.assertEqual({path.name: path.read_bytes() for path in paths}, previous)
        self.assertEqual(
            {path.name: stat.S_IMODE(path.stat().st_mode) for path in paths}, modes,
        )
        self.assertEqual(logged.count("Preserved existing"), 3)
        self.assertNotIn(different_status["SERVICE_ROLE_KEY"], logged)

    def test_default_configuration_does_not_create_administrative_integration_file(self):
        self.run_configuration()

        self.assertEqual(
            {path.name for path in self.output.iterdir()},
            {"backend.env", "client.env"},
        )

    def test_rejects_remote_or_wrong_protocol_database_before_creating_files(self):
        for url in (
            "postgresql://postgres:test-only-password@remote.example:5432/postgres",
            "postgresql://postgres:test-only-password@127.0.0.1.remote.example:5432/postgres",
            "https://postgres:test-only-password@127.0.0.1:54322/postgres",
        ):
            with self.subTest(url=url):
                with self.assertRaises(SystemExit):
                    self.run_configuration({**self.status, "DB_URL": url}, "--integration")
                self.assertEqual(list(self.output.iterdir()), [])

    def test_rejects_administrative_keys_before_creating_client_assets(self):
        for key in (
            "sb_secret_test_only_administrative_fixture",
            legacy_key("service_role"),
        ):
            with self.subTest(key_type="JWT" if "." in key else "secret"):
                with self.assertRaises(SystemExit):
                    self.run_configuration({**self.status, "PUBLISHABLE_KEY": key})
                self.assertEqual(list(self.output.iterdir()), [])

    def test_accepts_legacy_anon_key_without_copying_server_credentials_to_client(self):
        status = {**self.status, "ANON_KEY": legacy_key("anon")}
        del status["PUBLISHABLE_KEY"]

        logged = self.run_configuration(status)

        client = (self.output / "client.env").read_text(encoding="utf-8")
        self.assertIn(status["ANON_KEY"], client)
        self.assertNotIn(status["SERVICE_ROLE_KEY"], client)
        self.assertNotIn(status["ANON_KEY"], logged)

    def test_rejects_unsafe_env_values_without_leaving_a_partial_file(self):
        path = self.output / "backend.env"
        for unsafe in ("unexpected\nSECOND=value", "unexpected\rvalue", "unescaped'quote", "back\\slash"):
            with self.subTest(character=repr(unsafe)):
                with self.assertRaises(ValueError):
                    configure.write_new(path, {"FIRST": "safe", "SECOND": unsafe})
                self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
