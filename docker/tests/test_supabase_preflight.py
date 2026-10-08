import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


MOUNTED_SCRIPT = Path("/workspace/scripts/supabase-local.sh")
REPOSITORY_SCRIPT = Path(__file__).resolve().parents[2] / "scripts/supabase-local.sh"
PROJECT = "agrifos-it-12ab34cd"
FOREIGN_CONTAINER = "unrelated-existing-container"

# This executable models only Docker responses and local inventory. It cannot
# access a daemon, network, or the real Docker command.
FAKE_DOCKER = r'''
import json
import os
from pathlib import Path
import sys

arguments = sys.argv[1:]
calls = Path(os.environ["PREFLIGHT_CALLS"])
with calls.open("a", encoding="utf-8") as stream:
    stream.write(json.dumps({"tool": "docker", "arguments": arguments}) + "\n")
state_path = Path(os.environ["PREFLIGHT_STATE"])
state = json.loads(state_path.read_text())
behavior = json.loads(os.environ["PREFLIGHT_BEHAVIOR"])

def save():
    state_path.write_text(json.dumps(state))

def option(name):
    return arguments[arguments.index(name) + 1]

if arguments[:2] == ["image", "inspect"]:
    if behavior.get("missing_image"):
        sys.exit(1)
    print(behavior.get("image_volumes", 0))
elif arguments[:1] == ["ps"]:
    if behavior.get("listing_error"):
        sys.exit(1)
    if behavior.get("name_collision"):
        name = option("--filter").removeprefix("name=^").removesuffix("$")
        state["containers"][name] = {"labels": {"com.agrifos.managed-by": "someone-else"}}
        state["collision"] = name
        save()
        print(name)
elif arguments[:1] == ["create"]:
    name = option("--name")
    labels = {}
    for index, argument in enumerate(arguments):
        if argument == "--label":
            key, value = arguments[index + 1].split("=", 1)
            labels[key] = value
    state["containers"][name] = {"labels": labels}
    state["created"].append(name)
    save()
    if behavior.get("creation_error"):
        sys.exit(1)
    print("test-only-created-container-id")
elif arguments[:1] == ["start"]:
    if behavior.get("startup_error"):
        sys.exit(1)
    print(arguments[-1])
elif arguments[:1] == ["inspect"]:
    name = arguments[-1]
    if name not in state["containers"]:
        sys.exit(1)
    template = option("--format")
    if ".Config.Labels" in template:
        if behavior.get("identity_inspection_error"):
            sys.exit(1)
        labels = {**state["containers"][name]["labels"], **behavior.get("identity_labels", {})}
        identity = "|".join(labels.get(key, "") for key in (
            "com.agrifos.managed-by", "com.agrifos.project", "com.agrifos.probe-token",
        ))
        print(behavior.get("identity", identity))
    elif ".State.Running" in template:
        if behavior.get("running_inspection_error"):
            sys.exit(1)
        print(behavior.get("running", "true"))
    elif ".NetworkSettings.Ports" in template:
        if behavior.get("port_inspection_error"):
            sys.exit(1)
        print(behavior.get("bindings", "127.0.0.1:43123"))
    else:
        sys.exit("Unexpected Docker inspection")
elif arguments[:1] == ["rm"]:
    if behavior.get("removal_error"):
        sys.exit(1)
    name = arguments[-1]
    del state["containers"][name]
    state["removed"].append(name)
    save()
else:
    sys.exit("Unexpected Docker operation")
'''

FAKE_CLI = r'''
import json
import os
from pathlib import Path
import sys

with Path(os.environ["PREFLIGHT_CALLS"]).open("a", encoding="utf-8") as stream:
    stream.write(json.dumps({"tool": "supabase", "arguments": sys.argv[1:]}) + "\n")
'''


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux-only Bash safety tests; run in the backend-unit Docker service.")
class SupabaseLoopbackPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("bash") or not shutil.which("timeout"):
            raise unittest.SkipTest("The Linux preflight requires Bash and GNU timeout.")
        source = (MOUNTED_SCRIPT if MOUNTED_SCRIPT.is_file() else REPOSITORY_SCRIPT).read_text(encoding="utf-8")
        match = re.search(r"^preflight_loopback_binding\(\) \(\n.*?^\)$", source, re.MULTILINE | re.DOTALL)
        if match is None:
            raise AssertionError("The real Supabase loopback preflight function was not found.")
        cls.preflight = match.group(0)

    def run_preflight(self, **behavior):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            calls_path = directory / "calls.jsonl"
            state_path = directory / "state.json"
            state_path.write_text(json.dumps({
                "containers": {FOREIGN_CONTAINER: {"labels": {"com.agrifos.project": "other-project"}}},
                "created": [], "removed": [],
            }))
            for name, body in (("docker", FAKE_DOCKER), ("supabase", FAKE_CLI)):
                executable = directory / name
                executable.write_text(f"#!{sys.executable}\n{body}\n", encoding="utf-8")
                executable.chmod(0o755)
            environment = {
                **os.environ,
                "PATH": str(directory) + os.pathsep + os.environ["PATH"],
                "PREFLIGHT_CALLS": str(calls_path),
                "PREFLIGHT_STATE": str(state_path),
                "PREFLIGHT_BEHAVIOR": json.dumps(behavior),
            }
            harness = (
                "set -Eeuo pipefail\n"
                "fail() { printf 'Error: %s\\n' \"$*\" >&2; exit 1; }\n"
                f"project_id={PROJECT}\nnetwork={PROJECT}\n"
                + self.preflight
                + "\npreflight_loopback_binding\nsupabase start\n"
            )
            result = subprocess.run(
                ["bash", "-c", harness], env=environment,
                capture_output=True, text=True, timeout=30,
            )
            calls = [json.loads(line) for line in calls_path.read_text().splitlines()]
            state = json.loads(state_path.read_text())
        self.assertIn(FOREIGN_CONTAINER, state["containers"])
        self.assertEqual(
            state["containers"][FOREIGN_CONTAINER]["labels"],
            {"com.agrifos.project": "other-project"},
        )
        return result, calls, state

    def assert_cli_blocked(self, result, calls):
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(call["tool"] == "supabase" for call in calls))

    def assert_only_created_probe_removed(self, calls, state):
        self.assertEqual(len(state["created"]), 1)
        self.assertEqual(state["removed"], state["created"])
        removal_calls = [call["arguments"] for call in calls if call["tool"] == "docker" and call["arguments"][0] == "rm"]
        self.assertEqual(len(removal_calls), 1)
        self.assertEqual(removal_calls[0][-1], state["created"][0])
        create = next(call["arguments"] for call in calls if call["tool"] == "docker" and call["arguments"][0] == "create")
        labels = [create[index + 1] for index, argument in enumerate(create) if argument == "--label"]
        self.assertIn("com.agrifos.managed-by=supabase-local.sh", labels)
        self.assertIn(f"com.agrifos.project={PROJECT}", labels)
        self.assertTrue(any(label.startswith("com.agrifos.probe-token=") and label.partition("=")[2] for label in labels))
        self.assertEqual(set(state["containers"]), {FOREIGN_CONTAINER})

    def test_wildcard_bindings_block_cli_and_remove_only_the_created_probe(self):
        for bindings in ("0.0.0.0:43123", ":::43123", "127.0.0.1:43123\n0.0.0.0:43123"):
            with self.subTest(bindings=bindings):
                result, calls, state = self.run_preflight(bindings=bindings)
                self.assert_cli_blocked(result, calls)
                self.assert_only_created_probe_removed(calls, state)

    def test_loopback_binding_allows_cli_and_removes_only_the_created_probe(self):
        result, calls, state = self.run_preflight()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([call["arguments"] for call in calls if call["tool"] == "supabase"], [["start"]])
        self.assert_only_created_probe_removed(calls, state)

    def test_identity_mismatch_preserves_probe_and_blocks_cli(self):
        for labels in (
            {"com.agrifos.managed-by": "someone-else"},
            {"com.agrifos.project": "other-project"},
            {"com.agrifos.probe-token": "foreign-token"},
        ):
            with self.subTest(labels=labels):
                result, calls, state = self.run_preflight(identity_labels=labels)
                self.assert_cli_blocked(result, calls)
                self.assertEqual(state["removed"], [])
                self.assertEqual(set(state["containers"]), {FOREIGN_CONTAINER, state["created"][0]})

    def test_identity_inspection_error_preserves_resources_and_blocks_cli(self):
        result, calls, state = self.run_preflight(identity_inspection_error=True)

        self.assert_cli_blocked(result, calls)
        self.assertEqual(state["removed"], [])
        self.assertIn(state["created"][0], state["containers"])

    def test_missing_image_blocks_cli_without_creating_or_removing_resources(self):
        result, calls, state = self.run_preflight(missing_image=True)

        self.assert_cli_blocked(result, calls)
        self.assertEqual(state["created"], [])
        self.assertEqual(state["removed"], [])

    def test_image_with_volumes_is_rejected_before_creating_resources(self):
        result, calls, state = self.run_preflight(image_volumes=1)

        self.assert_cli_blocked(result, calls)
        self.assertEqual(state["created"], [])
        self.assertEqual(state["removed"], [])

    def test_listing_error_blocks_cli_without_creating_or_removing_resources(self):
        result, calls, state = self.run_preflight(listing_error=True)

        self.assert_cli_blocked(result, calls)
        self.assertEqual(state["created"], [])
        self.assertEqual(state["removed"], [])

    def test_preexisting_probe_name_is_preserved_without_attempted_cleanup(self):
        result, calls, state = self.run_preflight(name_collision=True)

        self.assert_cli_blocked(result, calls)
        self.assertEqual(state["created"], [])
        self.assertEqual(state["removed"], [])
        self.assertIn(state["collision"], state["containers"])

    def test_probe_inspection_errors_block_cli_and_clean_up_only_owned_probe(self):
        for failure in ("running_inspection_error", "port_inspection_error"):
            with self.subTest(failure=failure):
                result, calls, state = self.run_preflight(**{failure: True})
                self.assert_cli_blocked(result, calls)
                self.assert_only_created_probe_removed(calls, state)

    def test_nonrunning_or_unpublished_probe_is_rejected_and_cleaned_up(self):
        for behavior in ({"running": "false"}, {"bindings": ""}):
            with self.subTest(behavior=behavior):
                result, calls, state = self.run_preflight(**behavior)
                self.assert_cli_blocked(result, calls)
                self.assert_only_created_probe_removed(calls, state)

    def test_creation_or_start_failure_cleans_up_only_owned_probe(self):
        for failure in ("creation_error", "startup_error"):
            with self.subTest(failure=failure):
                result, calls, state = self.run_preflight(**{failure: True})
                self.assert_cli_blocked(result, calls)
                self.assert_only_created_probe_removed(calls, state)

    def test_cleanup_failure_blocks_cli_and_preserves_probe_for_inspection(self):
        result, calls, state = self.run_preflight(removal_error=True)

        self.assert_cli_blocked(result, calls)
        self.assertEqual(state["removed"], [])
        self.assertIn(state["created"][0], state["containers"])


if __name__ == "__main__":
    unittest.main()
