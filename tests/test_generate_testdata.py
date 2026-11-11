"""Tests für den Testdaten-Generator.

Aufruf aus dem Projektordner:
    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import filecmp
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "testdata"))

import generate_testdata as gen  # noqa: E402

DATA = gen.generate()
GT = DATA["ground_truth"]
BASE = [d for d in DATA["devices"] if d["source"] == gen.SOURCE_INVENTORY]
SCAN = [d for d in DATA["devices"] if d["source"] == gen.SOURCE_SCAN]
BY_ID = {d["source_id"]: d for d in DATA["devices"]}


def issue_ids(kind: str) -> set[str]:
    return {i["source_id"] for i in GT["issues"] if i["type"] == kind}


def ids(devices) -> set[str]:
    return {d["source_id"] for d in devices}


class Determinism(unittest.TestCase):
    def test_same_seed_same_data(self):
        self.assertEqual(gen.generate(), gen.generate())

    def test_other_seed_other_data(self):
        self.assertNotEqual(gen.generate(seed=1)["devices"], DATA["devices"])

    def test_files_identical_across_processes(self):
        """Gleiche Dateien, auch wenn Python Zeichenketten anders hasht."""
        script = ROOT / "testdata" / "generate_testdata.py"
        with tempfile.TemporaryDirectory() as tmp:
            outs = []
            for hash_seed in ("1", "2"):
                out = Path(tmp) / hash_seed
                env = {**os.environ, "PYTHONHASHSEED": hash_seed}
                subprocess.run([sys.executable, str(script), "--out", str(out)],
                               check=True, capture_output=True, env=env)
                outs.append(out)
            names = sorted(p.name for p in outs[0].iterdir())
            match, mismatch, errors = filecmp.cmpfiles(outs[0], outs[1], names, shallow=False)
            self.assertEqual((mismatch, errors), ([], []))


class Volumes(unittest.TestCase):
    def test_device_counts(self):
        self.assertEqual(len(BASE), gen.DEFAULT_COUNT)
        self.assertEqual(len(SCAN), GT["counts"]["devices_scan_duplicates"])
        self.assertEqual(sum(gen.category_counts(gen.DEFAULT_COUNT).values()), gen.DEFAULT_COUNT)

    def test_other_count_works(self):
        data = gen.generate(seed=3, count=gen.MIN_COUNT)
        self.assertEqual(data["ground_truth"]["counts"]["devices_inventory"], gen.MIN_COUNT)

    def test_too_small_count_rejected(self):
        with self.assertRaises(ValueError):
            gen.generate(count=gen.MIN_COUNT - 1)


class Plausibility(unittest.TestCase):
    def test_unique_keys(self):
        for field in ("source_id", "asset_tag", "name", "mac_address"):
            values = [d[field] for d in BASE]
            self.assertEqual(len(values), len(set(values)), field)
        serials = [d["serial_number"] for d in BASE if d["serial_number"]]
        self.assertEqual(len(serials), len(set(serials)))
        user_names = [u["user_name"] for u in DATA["users"]]
        self.assertEqual(len(user_names), len(set(user_names)))

    def test_dates(self):
        ref = date.fromisoformat(GT["parameters"]["reference_date"])
        for d in BASE:
            purchase = date.fromisoformat(d["purchase_date"])
            self.assertLess(purchase, ref)
            self.assertGreater(date.fromisoformat(d["warranty_expiration"]), purchase)

    def test_models_match_purchase_year(self):
        model = {(m.manufacturer, m.name): m for m in gen.MODELS}
        canonical = {m.name: m.manufacturer for m in gen.MODELS}
        for d in BASE:
            m = model[(canonical[d["model_id"]], d["model_id"])]
            self.assertTrue(m.year_from <= int(d["purchase_date"][:4]) <= m.year_to, d["source_id"])

    def test_only_fictional_contact_data(self):
        for u in DATA["users"]:
            self.assertTrue(u["email"].endswith("@" + gen.DOMAIN), u["email"])
        for d in DATA["devices"]:
            self.assertTrue(d["mac_address"].startswith("02:"), d["mac_address"])
            if d["ip_address"]:
                self.assertTrue(d["ip_address"].startswith("10."), d["ip_address"])

    def test_company_set_everywhere(self):
        """Alle Datensätze tragen die Testfirma, damit sie sich von den Demo-Daten der PDI trennen lassen."""
        for table in ("devices", "users", "locations", "departments"):
            for row in DATA[table]:
                self.assertEqual(row["company"], gen.COMPANY, table)

    def test_smartphones_use_class_with_ire_rule(self):
        for d in DATA["devices"]:
            if d["category"] == "smartphone":
                self.assertEqual(d["sn_class"], "cmdb_ci_hardware")

    def test_references_exist(self):
        users = {u["user_name"] for u in DATA["users"]}
        locations = {loc["name"] for loc in DATA["locations"]} | {""}
        departments = {dep["name"] for dep in DATA["departments"]} | {""}
        for d in DATA["devices"]:
            self.assertIn(d["assigned_to"], users | {""})
            self.assertIn(d["location"], locations)
            self.assertIn(d["department"], departments)

    def test_software_tables_consistent(self):
        products = {s.product for s in gen.SOFTWARE}
        for table in (gen.SOFTWARE_BASELINE, gen.SOFTWARE_RANDOM_EXTRAS, gen.LICENSE_PLAN,
                      *gen.SOFTWARE_BY_DEPARTMENT.values()):
            self.assertLessEqual(set(table), products)
        self.assertLessEqual(set(gen.SOFTWARE_BY_DEPARTMENT), {name for name, _, _ in gen.DEPARTMENTS})

    def test_installations_only_on_computers_in_use(self):
        for inst in DATA["installations"]:
            d = BY_ID[inst["device_source_id"]]
            self.assertEqual(d["source"], gen.SOURCE_INVENTORY)
            self.assertIn(d["category"], gen.COMPUTERS)
            self.assertIn(d["install_status"], gen.IN_USE)
            self.assertEqual(inst["installed_on"], d["name"])


class GroundTruth(unittest.TestCase):
    """Die Fehlerliste muss genau die Datensätze nennen, die den Fehler haben:
    keine fehlenden und keine zufällig zusätzlichen."""

    def test_issue_counts_match_list(self):
        for kind in gen.ISSUE_TYPES:
            self.assertEqual(GT["issue_counts"].get(kind, 0), len(issue_ids(kind)), kind)
            self.assertGreater(len(issue_ids(kind)), 0, kind)

    def test_at_most_one_issue_per_device(self):
        listed = [i["source_id"] for i in GT["issues"]]
        self.assertEqual(len(listed), len(set(listed)))

    def test_missing_serial_number(self):
        self.assertEqual(ids(d for d in BASE if not d["serial_number"]), issue_ids("missing_serial_number"))

    def test_missing_location(self):
        self.assertEqual(ids(d for d in BASE if not d["location"]), issue_ids("missing_location"))

    def test_manufacturer_variants(self):
        canonical = {m.manufacturer for m in gen.MODELS}
        found = ids(d for d in BASE if d["manufacturer"] not in canonical)
        self.assertEqual(found, issue_ids("manufacturer_name_variant"))

    def test_installed_without_user(self):
        found = ids(d for d in BASE if d["category"] in gen.ENDPOINTS
                    and d["install_status"] in gen.IN_USE and not d["assigned_to"])
        self.assertEqual(found, issue_ids("installed_without_user"))

    def test_retired_with_user(self):
        found = ids(d for d in BASE if d["install_status"] == gen.RETIRED and d["assigned_to"])
        self.assertEqual(found, issue_ids("retired_with_user"))

    def test_assigned_to_inactive_user(self):
        inactive = {u["user_name"] for u in DATA["users"] if u["active"] == "false"}
        found = ids(d for d in BASE if d["install_status"] in gen.IN_USE and d["assigned_to"] in inactive)
        self.assertEqual(found, issue_ids("assigned_to_inactive_user"))
        self.assertEqual(len(inactive), GT["counts"]["users_inactive"])

    def test_duplicates(self):
        duplicate_kinds = ("duplicate_same_serial", "duplicate_serial_variant", "duplicate_same_name_no_serial")
        self.assertEqual(ids(SCAN), set().union(*(issue_ids(k) for k in duplicate_kinds)))
        for issue in GT["issues"]:
            if issue["type"] not in duplicate_kinds:
                continue
            dup, orig = BY_ID[issue["source_id"]], BY_ID[issue["duplicate_of"]]
            self.assertEqual(orig["source"], gen.SOURCE_INVENTORY)
            self.assertTrue(orig["serial_number"])
            if issue["type"] == "duplicate_same_serial":
                self.assertEqual(dup["serial_number"], orig["serial_number"])
                self.assertEqual(dup["name"], f"{orig['name'].lower()}.{gen.DOMAIN}")
                self.assertEqual(dup["mac_address"], orig["mac_address"])
            elif issue["type"] == "duplicate_serial_variant":
                self.assertNotEqual(dup["serial_number"], orig["serial_number"])
                self.assertEqual(dup["serial_number"].strip().upper(), orig["serial_number"])
                # Kein Treffer über MAC oder IP möglich, nur über die Seriennummer
                self.assertNotIn(dup["mac_address"], {d["mac_address"] for d in BASE})
                self.assertEqual(dup["ip_address"], "")
            else:
                self.assertEqual(dup["serial_number"], "")
                self.assertEqual(dup["name"], orig["name"])
                self.assertEqual(dup["mac_address"], orig["mac_address"])


class Licensing(unittest.TestCase):
    def test_usage_recount(self):
        """Nutzung unabhängig vom Generator nachzählen."""
        product_of = {s.display_name: s for s in gen.SOFTWARE}
        for row in GT["sam"]:
            devices = {i["device_source_id"] for i in DATA["installations"]
                       if product_of[i["display_name"]].product == row["product"]}
            if row["metric"] == "Per Device":
                expected = len(devices)
            else:
                assigned = [BY_ID[i]["assigned_to"] for i in devices]
                expected = len({u for u in assigned if u}) + assigned.count("")
            self.assertEqual(row["usage"], expected, row["product"])
            self.assertEqual(row["difference"], row["purchased_rights"] - row["usage"], row["product"])

    def test_every_status_present(self):
        statuses = {row["status"] for row in GT["sam"]}
        self.assertLessEqual({"unterlizenziert", "überlizenziert", "ausgeglichen", "ohne Lizenz"}, statuses)
        for row in GT["sam"]:
            self.assertEqual(row["status"] == "ungenutzt", row["usage"] == 0 and row["purchased_rights"] > 0)


if __name__ == "__main__":
    unittest.main()
