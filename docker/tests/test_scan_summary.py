import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


spec = importlib.util.spec_from_file_location("scan_summary", Path(__file__).resolve().parents[1] / "scan_summary.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def evidence():
    digest = "sha256:" + "a" * 64
    inspected = "sha256:" + "b" * 64
    runtime = {"Metadata": {"ImageID": digest, "OS": {"Family": "debian", "Name": "13.7"}},
               "Results": [{"Type": "debian"}], "Trivy": {"Version": "0.75.0"}}
    config = {"Results": [{"Type": "dockerfile"}], "Trivy": {"Version": "0.75.0"}}
    identity = {"matches": True, "inspected_image_id": inspected,
                "archive_config_digest": digest, "trivy_image_id": digest}
    status = {"config_exit": 0, "image_exit": 0, "identity_exit": 0, "metadata_exit": 0,
              "database_exit": 0, "platform": "linux/amd64", "inspected_image_id": inspected}
    metadata = {"Version": "0.75.0", "VulnerabilityDB": {
        "Version": 2, "UpdatedAt": "2026-10-08T15:33:46.578791096Z",
        "NextUpdate": "2026-10-09T15:33:46.578790805Z", "DownloadedAt": "2026-10-08T16:34:48.095634265Z",
    }}
    return runtime, config, identity, status, metadata


def vulnerable(runtime):
    runtime["Results"][0]["Vulnerabilities"] = [{
        "VulnerabilityID": "CVE-2026-76642", "PkgName": "mount", "InstalledVersion": "2.41.5",
        "FixedVersion": "", "Severity": "HIGH", "Status": "affected",
    }]


class PublicScannerSummaryTests(unittest.TestCase):
    def test_secret_matches_environment_and_messages_are_not_published(self):
        private = "never-publish-this-secret"
        runtime = {"Metadata": {"ImageID": "sha256:" + "a" * 64, "ImageConfig": {"Env": [private]}},
                   "Results": [{"Target": private, "Secrets": [{"Match": private}],
                                "Misconfigurations": [{"Message": private}],
                                "Vulnerabilities": [{"VulnerabilityID": "CVE-2026-76642", "PkgName": "mount", "InstalledVersion": "2.41.5", "Severity": "HIGH", "Description": private}]}]}
        summary = module.summarize(runtime, runtime, {"matches": True, "unexpected": private})
        self.assertNotIn(private, json.dumps(summary))
        self.assertEqual(summary["vulnerability_counts"], {"HIGH": 1, "CRITICAL": 0})
        self.assertEqual(summary["secret_findings_count"], 1)
        self.assertTrue(summary["identity_matches"])

    def test_missing_report_is_not_misreported_as_zero_findings(self):
        summary = module.summarize(None, None, None)
        self.assertFalse(summary["runtime_report_available"])
        self.assertIsNone(summary["vulnerability_counts"])
        self.assertIsNone(summary["secret_findings_count"])
        self.assertIsNone(summary["identity_matches"])

    def test_complete_scan_passes_with_public_distribution_and_database_metadata(self):
        summary = module.summarize(*evidence())
        self.assertEqual(summary["gate_status"], "PASS")
        self.assertTrue(all(status == "PASS" for status in summary["stage_status"].values()))
        self.assertEqual(summary["runtime_distribution"], {"Family": "debian", "Name": "13.7"})
        self.assertEqual(summary["scanner_metadata"]["VulnerabilityDB"]["Version"], 2)

    def test_distinct_findings_exit_and_fatal_exit_are_classified_separately(self):
        for code, expected in ((10, "FAIL_FINDINGS"), (1, "FAIL_OPERATIONAL"), (125, "FAIL_OPERATIONAL")):
            with self.subTest(exit_code=code):
                documents = evidence()
                vulnerable(documents[0])
                documents[3]["image_exit"] = code
                summary = module.summarize(*documents)
                self.assertEqual(summary["gate_status"], expected)
                self.assertEqual(summary["vulnerability_counts"]["HIGH"], 1)

    def test_success_status_and_findings_status_must_agree_with_reports(self):
        for report_index, exit_field in ((0, "image_exit"), (1, "config_exit")):
            for has_findings, code in ((True, 0), (False, 10)):
                with self.subTest(scanner=exit_field, findings=has_findings, exit_code=code):
                    documents = evidence()
                    if has_findings:
                        documents[report_index]["Results"][0]["Misconfigurations"] = [{"Severity": "HIGH"}]
                    documents[3][exit_field] = code
                    self.assertEqual(module.summarize(*documents)["gate_status"], "FAIL_OPERATIONAL")

    def test_report_missing_after_scanner_failure_has_unknown_counts(self):
        documents = list(evidence())
        documents[0] = None
        documents[3]["image_exit"] = 1
        summary = module.summarize(*documents)
        self.assertEqual(summary["gate_status"], "FAIL_OPERATIONAL")
        self.assertIsNone(summary["vulnerability_counts"])
        self.assertIsNone(summary["secret_findings_count"])

    def test_malformed_shapes_fail_closed_without_publishing_raw_errors(self):
        for invalid in ({}, [], {"Results": "private-error"},
                        {"Results": [], "Metadata": {"ImageID": "private-error"}},
                        {"Results": [{"Vulnerabilities": False}], "Metadata": {"ImageID": "sha256:" + "a" * 64}},
                        {"Results": [{"Vulnerabilities": [{"Severity": {"private-error": 1}}]}], "Metadata": {"ImageID": "sha256:" + "a" * 64}}):
            with self.subTest(report=invalid):
                documents = list(evidence())
                documents[0] = invalid
                summary = module.summarize(*documents)
                self.assertEqual(summary["gate_status"], "FAIL_OPERATIONAL")
                self.assertIsNone(summary["vulnerability_counts"])
                self.assertNotIn("private-error", json.dumps(summary))

    def test_success_exit_requires_complete_identity_matching_the_inspected_image(self):
        for identity in (None, {"matches": True}, {"matches": False},
                         {**evidence()[2], "inspected_image_id": "sha256:" + "a" * 64},
                         {**evidence()[2], "archive_config_digest": "sha256:" + "b" * 64}):
            with self.subTest(identity=identity):
                documents = list(evidence())
                documents[2] = identity
                self.assertEqual(module.summarize(*documents)["gate_status"], "FAIL_OPERATIONAL")

    def test_all_stage_exits_are_required_and_unexecuted_is_not_pass(self):
        for field in module.EXIT_FIELDS:
            for invalid in (-1, None, False, "0"):
                with self.subTest(field=field, exit_code=invalid):
                    documents = evidence()
                    documents[3][field] = invalid
                    self.assertEqual(module.summarize(*documents)["gate_status"], "FAIL_OPERATIONAL")

    def test_database_metadata_is_required_and_unknown_fields_stay_private(self):
        for metadata in (None, {}, {"Version": "0.75.0", "VulnerabilityDB": {}},
                         {**evidence()[4], "Version": "private-version"}):
            with self.subTest(metadata=metadata):
                documents = list(evidence())
                documents[4] = metadata
                summary = module.summarize(*documents)
                self.assertEqual(summary["gate_status"], "FAIL_OPERATIONAL")
                self.assertIsNone(summary["scanner_metadata"])
                self.assertNotIn("private-version", json.dumps(summary))
        documents = evidence()
        documents[3]["Error"] = "private-raw-error"
        documents[4]["Environment"] = ["private-raw-error"]
        documents[4]["VulnerabilityDB"]["URL"] = "private-raw-error"
        self.assertNotIn("private-raw-error", json.dumps(module.summarize(*documents)))

    def test_report_scanner_version_and_platform_must_match(self):
        documents = evidence()
        documents[0]["Trivy"]["Version"] = "0.74.0"
        self.assertEqual(module.summarize(*documents)["gate_status"], "FAIL_OPERATIONAL")
        documents = evidence()
        documents[3]["platform"] = "linux/arm64"
        self.assertEqual(module.summarize(*documents)["gate_status"], "FAIL_OPERATIONAL")


class ScannerSummaryCliTests(unittest.TestCase):
    def run_summary(self, documents, enforce=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names = ("trivy-runtime.json", "trivy-config.json", "runtime-identity.json", "scan-status.json", "scanner-metadata.json")
            for name, document in zip(names, documents):
                if document is not None:
                    (root / name).write_text(document if isinstance(document, str) else json.dumps(document), encoding="utf-8")
            output = root / "public-summary.json"
            command = [sys.executable, str(Path(module.__file__)), str(root), str(output)]
            if enforce:
                command.append("--enforce")
            result = subprocess.run(command, capture_output=True, text=True)
            summary = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else None
            return result, summary

    def test_truncated_json_retains_a_sanitized_operational_failure_artifact(self):
        documents = list(evidence())
        documents[0] = '{"private-secret": "do-not-publish"'
        result, summary = self.run_summary(documents)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(summary["gate_status"], "FAIL_OPERATIONAL")
        self.assertIsNone(summary["vulnerability_counts"])
        self.assertNotIn("do-not-publish", json.dumps(summary) + result.stdout + result.stderr)

    def test_enforce_exit_codes_distinguish_all_four_outcomes(self):
        for expected_status, expected_exit in (("PASS", 0), ("FAIL_FINDINGS", 1), ("FAIL_OPERATIONAL", 1), ("NOT_RUN", 3)):
            with self.subTest(outcome=expected_status):
                documents = evidence()
                if expected_status == "FAIL_FINDINGS":
                    vulnerable(documents[0])
                    documents[3]["image_exit"] = 10
                elif expected_status == "FAIL_OPERATIONAL":
                    documents[3]["image_exit"] = 1
                elif expected_status == "NOT_RUN":
                    documents = (None,) * 5
                result, summary = self.run_summary(documents, enforce=True)
                self.assertEqual(result.returncode, expected_exit, result.stderr)
                self.assertEqual(summary["gate_status"], expected_status)

    def test_corrupt_status_and_metadata_remain_operational_with_good_reports(self):
        for index in (3, 4):
            with self.subTest(document=index):
                documents = list(evidence())
                documents[index] = '{"Error": "private-raw-error"'
                result, summary = self.run_summary(documents, enforce=True)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(summary["gate_status"], "FAIL_OPERATIONAL")
                self.assertNotIn("private-raw-error", json.dumps(summary) + result.stdout + result.stderr)

    def test_existing_json_null_is_invalid_evidence_not_an_unexecuted_scan(self):
        result, summary = self.run_summary(("null", None, None, None, None), enforce=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(summary["gate_status"], "FAIL_OPERATIONAL")
        self.assertIsNone(summary["vulnerability_counts"])
