import importlib.util
import json
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location("scan_summary", Path(__file__).resolve().parents[1] / "scan_summary.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


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
