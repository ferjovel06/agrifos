"""Publish only scanner counts and dependency metadata, never matched secrets."""
import json
from pathlib import Path
import re
import sys


def summarize(runtime, configuration, identity):
    results = (runtime or {}).get("Results", [])
    digest = (runtime or {}).get("Metadata", {}).get("ImageID")
    if digest is not None and not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("Invalid public image digest")
    vulnerabilities = [{
        key: finding.get(key) for key in (
            "VulnerabilityID", "PkgName", "InstalledVersion", "FixedVersion", "Severity", "Status",
        )
    } for result in results for finding in result.get("Vulnerabilities", [])]
    return {
        "runtime_report_available": runtime is not None,
        "configuration_report_available": configuration is not None,
        "image_config_digest": digest,
        "identity_matches": (identity or {}).get("matches"),
        "vulnerabilities": vulnerabilities if runtime is not None else None,
        "vulnerability_counts": {severity: sum(v["Severity"] == severity for v in vulnerabilities)
                                 for severity in ("HIGH", "CRITICAL")} if runtime is not None else None,
        "secret_findings_count": sum(len(result.get("Secrets", [])) for result in results) if runtime is not None else None,
        "runtime_misconfiguration_count": sum(len(result.get("Misconfigurations", [])) for result in results) if runtime is not None else None,
        "configuration_misconfiguration_count": sum(len(result.get("Misconfigurations", [])) for result in (configuration or {}).get("Results", [])) if configuration is not None else None,
    }


def main():
    directory, output = map(Path, sys.argv[1:])
    def read(name):
        path = directory / name
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    summary = summarize(read("trivy-runtime.json"), read("trivy-config.json"), read("runtime-identity.json"))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print("Scanner evidence:", summary["vulnerability_counts"], "identity matches:", summary["identity_matches"])


if __name__ == "__main__":
    main()
