import copy
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit_bindings import audit

PROJECT = "agrifos-it-1234abcd"


class BindingAuditTests(unittest.TestCase):
    def records(self):
        records = []
        for name in ("db", "auth", "kong", "inbucket", "api"):
            bindings = {} if name == "auth" else {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "54331"}]}
            records.append({
                "name": f"/{PROJECT}-api-1" if name == "api" else f"/supabase_{name}_{PROJECT}",
                "requested": copy.deepcopy(bindings), "actual": copy.deepcopy(bindings),
            })
        return records

    def test_accepts_complete_loopback_inventory(self):
        self.assertEqual(audit(self.records(), PROJECT), 4)

    def test_rejects_wildcard_ipv4_ipv6_and_lan(self):
        for address in ("", "0.0.0.0", "::", "192.168.1.4"):
            for field in ("requested", "actual"):
                records = self.records()
                records[0][field]["8000/tcp"][0]["HostIp"] = address
                with self.subTest(address=address, field=field), self.assertRaises(ValueError):
                    audit(records, PROJECT)

    def test_rejects_missing_foreign_and_duplicate_containers(self):
        records = self.records()
        for modified in (records[1:], records + [records[0]], [{**records[0], "name": "/foreign"}] + records[1:]):
            with self.assertRaises(ValueError):
                audit(modified, PROJECT)
        with self.assertRaises(ValueError):
            audit(records, "agrifos")

    def test_rejects_unresolved_and_zero_actual_ports(self):
        for entries in ([], [{"HostIp": "127.0.0.1", "HostPort": "0"}]):
            records = self.records()
            records[0]["actual"]["8000/tcp"] = entries
            with self.assertRaises(ValueError):
                audit(records, PROJECT)
