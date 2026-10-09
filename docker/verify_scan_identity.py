"""Tie the exported immutable image's config digest to the Trivy report."""
import hashlib
import json
from pathlib import Path
import sys
import tarfile

archive, report, proof, inspected_id = sys.argv[1:]
with tarfile.open(archive) as image:
    manifests = json.load(image.extractfile("manifest.json"))
    if len(manifests) != 1:
        raise SystemExit("FAIL: ambiguous exported runtime manifest")
    config = image.extractfile(manifests[0]["Config"]).read()
    digest = "sha256:" + hashlib.sha256(config).hexdigest()
scan_id = json.loads(Path(report).read_text(encoding="utf-8"))["Metadata"]["ImageID"]
record = {"inspected_image_id": inspected_id, "archive_config_digest": digest,
          "trivy_image_id": scan_id, "matches": digest == scan_id}
Path(proof).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
if digest != scan_id:
    raise SystemExit("FAIL: Trivy report does not match the exported runtime config")
print("PASS: Trivy report matches the immutable exported runtime's config digest.")
