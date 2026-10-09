"""Evaluate scanner evidence without publishing secret matches or raw errors."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys


INVALID_DOCUMENT = object()
EXIT_FIELDS = ("config_exit", "image_exit", "identity_exit", "metadata_exit", "database_exit")
PUBLIC_FIELDS = ("VulnerabilityID", "PkgName", "InstalledVersion", "FixedVersion", "Severity", "Status")
SEVERITIES = {"UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL"}
FINDINGS_EXIT_CODE = 10


def digest(value):
    return value if isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value) else None


def valid_report(report, runtime=False):
    if not isinstance(report, dict) or not isinstance(report.get("Results"), list):
        return False
    if runtime and (not isinstance(report.get("Metadata"), dict) or digest(report["Metadata"].get("ImageID")) is None):
        return False
    for result in report["Results"]:
        if not isinstance(result, dict):
            return False
        for field in ("Vulnerabilities", "Secrets", "Misconfigurations"):
            findings = result.get(field)
            if findings is None:
                continue
            if not isinstance(findings, list) or any(not isinstance(item, dict) for item in findings):
                return False
            if field == "Vulnerabilities":
                for finding in findings:
                    if not isinstance(finding.get("Severity"), str) or finding["Severity"] not in SEVERITIES:
                        return False
                    if any(finding.get(key) is not None and not isinstance(finding[key], str) for key in PUBLIC_FIELDS):
                        return False
    return True


def findings(report, field):
    return [item for result in report["Results"] for item in result.get(field) or []]


def public_metadata(metadata):
    if not isinstance(metadata, dict):
        return None
    version = metadata.get("Version")
    database = metadata.get("VulnerabilityDB")
    if not isinstance(version, str) or not re.fullmatch(r"v?\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?", version) or not isinstance(database, dict):
        return None
    if type(database.get("Version")) is not int or database["Version"] <= 0:
        return None
    selected = {"Version": database["Version"]}
    for key in ("UpdatedAt", "NextUpdate", "DownloadedAt"):
        value = database.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})", value):
            return None
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        selected[key] = value
    return {"Version": version, "VulnerabilityDB": selected}


def summarize(runtime, configuration, identity, scan_status=None, scanner_metadata=None):
    """Preserve the three-argument API and fail closed when gate evidence is absent."""
    runtime_valid, config_valid = valid_report(runtime, True), valid_report(configuration)
    status = scan_status if isinstance(scan_status, dict) else {}
    exits = {key: status.get(key) if type(status.get(key)) is int and -1 <= status[key] <= 255 else None for key in EXIT_FIELDS}
    platform = status.get("platform")
    if not isinstance(platform, str) or not re.fullmatch(r"[a-z0-9]+/[a-z0-9]+(?:/[a-z0-9]+)?", platform):
        platform = None
    inspected = digest(status.get("inspected_image_id"))
    image_digest = runtime["Metadata"]["ImageID"] if runtime_valid else None
    matches = identity.get("matches") if isinstance(identity, dict) else None
    matches = matches if type(matches) is bool else None
    distribution = runtime.get("Metadata", {}).get("OS") if runtime_valid else None
    if isinstance(distribution, dict) and all(isinstance(distribution.get(key), str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,79}", distribution[key]) for key in ("Family", "Name")):
        distribution = {key: distribution[key] for key in ("Family", "Name")}
    else:
        distribution = None
    metadata = public_metadata(scanner_metadata)
    vulnerabilities = [{key: item.get(key) for key in PUBLIC_FIELDS} for item in findings(runtime, "Vulnerabilities")] if runtime_valid else None
    counts = {severity: sum(item["Severity"] == severity for item in vulnerabilities) for severity in ("HIGH", "CRITICAL")} if runtime_valid else None
    secrets = len(findings(runtime, "Secrets")) if runtime_valid else None
    runtime_misconfig = len(findings(runtime, "Misconfigurations")) if runtime_valid else None
    config_misconfig = len(findings(configuration, "Misconfigurations")) if config_valid else None
    config_secrets = len(findings(configuration, "Secrets")) if config_valid else None
    summary = {
        "schema_version": 2,
        "runtime_report_available": runtime_valid, "configuration_report_available": config_valid,
        "image_config_digest": image_digest, "inspected_image_id": inspected, "image_platform": platform,
        "runtime_distribution": distribution, "identity_matches": matches, "scanner_metadata": metadata,
        "scanner_exit_codes": exits, "vulnerabilities": vulnerabilities, "vulnerability_counts": counts,
        "secret_findings_count": secrets, "runtime_misconfiguration_count": runtime_misconfig,
        "configuration_misconfiguration_count": config_misconfig, "configuration_secret_findings_count": config_secrets,
    }
    stages = {name: "NOT_RUN" for name in ("configuration", "runtime", "identity", "metadata", "database")}
    errors = []
    if all(document is None for document in (runtime, configuration, identity, scan_status, scanner_metadata)):
        summary.update(gate_status="NOT_RUN", stage_status=stages, operational_errors=errors)
        return summary

    def operational(stage, reason):
        stages[stage] = "FAIL_OPERATIONAL"
        errors.append(reason)

    for stage, field, report, valid, count in (
        ("runtime", "image_exit", runtime, runtime_valid, sum(counts.values()) + secrets + runtime_misconfig if runtime_valid else None),
        ("configuration", "config_exit", configuration, config_valid, config_misconfig + config_secrets if config_valid else None),
    ):
        if not valid:
            operational(stage, f"{stage}_report_missing" if report is None else f"{stage}_report_invalid")
        elif exits[field] not in (0, FINDINGS_EXIT_CODE):
            operational(stage, f"{stage}_exit_not_success_or_findings")
        elif (exits[field] == FINDINGS_EXIT_CODE) != bool(count):
            operational(stage, f"{stage}_exit_report_inconsistent")
        else:
            stages[stage] = "FAIL_FINDINGS" if count else "PASS"
    if scan_status is None:
        errors.append("scan_status_missing")
    elif not isinstance(scan_status, dict):
        errors.append("scan_status_invalid")
    if platform != "linux/amd64":
        errors.append("image_platform_missing_or_unsupported")
    if inspected is None:
        errors.append("inspected_image_id_missing_or_invalid")
    if runtime_valid and distribution is None:
        errors.append("runtime_distribution_missing_or_invalid")
    identity_valid = isinstance(identity, dict) and matches is True and image_digest is not None and inspected is not None
    if identity_valid:
        identity_valid = (identity.get("inspected_image_id") == inspected and identity.get("archive_config_digest") == image_digest and identity.get("trivy_image_id") == image_digest)
    if exits["identity_exit"] != 0 or not identity_valid:
        operational("identity", "identity_verification_missing_failed_or_inconsistent")
    else:
        stages["identity"] = "PASS"
    for stage, field in (("metadata", "metadata_exit"), ("database", "database_exit")):
        if exits[field] != 0 or metadata is None:
            operational(stage, f"{stage}_verification_missing_or_failed")
        else:
            stages[stage] = "PASS"
    if metadata is not None:
        for stage, report, valid in (("runtime", runtime, runtime_valid), ("configuration", configuration, config_valid)):
            reported_version = report.get("Trivy", {}).get("Version") if valid and isinstance(report.get("Trivy", {}), dict) else None
            if reported_version is not None and reported_version != metadata["Version"]:
                operational(stage, f"{stage}_scanner_version_inconsistent")
    gate = "FAIL_OPERATIONAL" if errors else "FAIL_FINDINGS" if "FAIL_FINDINGS" in stages.values() else "PASS"
    summary.update(gate_status=gate, stage_status=stages, operational_errors=sorted(set(errors)))
    return summary


def read(path):
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        return INVALID_DOCUMENT if document is None else document
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError):
        return INVALID_DOCUMENT


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--enforce", action="store_true")
    args = parser.parse_args(argv)
    summary = summarize(*(read(args.directory / name) for name in (
        "trivy-runtime.json", "trivy-config.json", "runtime-identity.json", "scan-status.json", "scanner-metadata.json",
    )))
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    except (OSError, UnicodeError, ValueError):
        print("FAIL_OPERATIONAL: public scanner summary could not be written.", file=sys.stderr)
        return 2
    print("Scanner evidence:", summary["gate_status"], summary["vulnerability_counts"], "identity matches:", summary["identity_matches"])
    return {"PASS": 0, "FAIL_FINDINGS": 1, "FAIL_OPERATIONAL": 1, "NOT_RUN": 3}[summary["gate_status"]] if args.enforce else 0


if __name__ == "__main__":
    sys.exit(main())
