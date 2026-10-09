"""Reject mismatched or ambiguous evidence without depending on a local image tag."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "verify_scan_identity.py"


class ScanIdentityTests(unittest.TestCase):
    def verify(self, *, mismatch=False, ambiguous=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = b'{"config":{"User":"10001"}}'
            digest = "sha256:" + hashlib.sha256(config).hexdigest()
            manifest = [{"Config": "config.json"}] * (2 if ambiguous else 1)
            with tarfile.open(root / "image.tar", "w") as archive:
                for name, data in (("config.json", config), ("manifest.json", json.dumps(manifest).encode())):
                    item = tarfile.TarInfo(name)
                    item.size = len(data)
                    archive.addfile(item, io.BytesIO(data))
            (root / "report.json").write_text(json.dumps({
                "Metadata": {"ImageID": "sha256:tampered" if mismatch else digest},
            }), encoding="utf-8")
            result = subprocess.run([
                sys.executable, str(SCRIPT), str(root / "image.tar"),
                str(root / "report.json"), str(root / "proof.json"), "sha256:exported-index",
            ], capture_output=True, text=True)
            proof = json.loads((root / "proof.json").read_text(encoding="utf-8")) if (root / "proof.json").exists() else None
            return result, proof

    def test_matching_archive_passes_without_access_to_docker_or_a_local_tag(self):
        result, proof = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(proof["matches"])
        self.assertEqual(proof["inspected_image_id"], "sha256:exported-index")

    def test_tampered_report_is_a_failure_with_negative_evidence(self):
        result, proof = self.verify(mismatch=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(proof["matches"])

    def test_ambiguous_manifest_is_rejected_without_a_positive_proof(self):
        result, proof = self.verify(ambiguous=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(proof)
