"""Tests für die Berechnung der Lizenzposition (ohne Netzwerk)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "loader"))
sys.path.insert(0, str(ROOT / "testdata"))

import generate_testdata as gen  # noqa: E402
from check_license_position import (  # noqa: E402
    METRIC,
    PER_DEVICE,
    PER_USER,
    STATUS_EN,
    compare,
    compute_position,
    expected_rows,
    license_status,
)

DATA = gen.generate()
SCRIPT = (ROOT / "servicenow" / "license_position.js").read_text(encoding="utf-8")


def instance_like() -> tuple[list[dict], list[dict], dict[str, dict]]:
    """Die Testdaten so, wie sie nach dem Import in der Instanz stehen (Modell-ID = Produktname)."""
    product_of = {s.display_name: s.product for s in gen.SOFTWARE}
    user_of = {d["source_id"]: d["assigned_to"] for d in DATA["devices"]}
    installations = [{"model": product_of[i["display_name"]], "device": i["device_source_id"],
                      "user": user_of[i["device_source_id"]]} for i in DATA["installations"]]
    licenses = [{"model": e["product"], "rights": e["purchased_rights"]} for e in DATA["entitlements"]]
    models = {s.product: {"product": s.product, "publisher": s.publisher, "metric": METRIC.get(s.license_metric, "")}
              for s in gen.SOFTWARE}
    return installations, licenses, models


class Position(unittest.TestCase):
    def test_recalculation_matches_ground_truth(self):
        """Die Zählweise der Prüfung ist dieselbe wie im Generator: alle 9 Produkte stimmen."""
        rows = compute_position(*instance_like())
        expected = expected_rows(DATA["ground_truth"])
        self.assertEqual(len(expected), 9)
        self.assertEqual(compare(rows, expected), {e["product"]: [] for e in expected})

    def test_free_software_without_license_is_left_out(self):
        products = {r["product"] for r in compute_position(*instance_like())}
        self.assertNotIn("Chrome", products)
        self.assertIn("WinRAR", products)  # lizenzpflichtig, aber keine Lizenz

    def test_status_rules(self):
        self.assertEqual(license_status(False, 0, 10), "ohne Lizenz")
        self.assertEqual(license_status(True, 1, 0), "ungenutzt")
        self.assertEqual(license_status(True, 9, 11), "unterlizenziert")
        self.assertEqual(license_status(True, 13, 10), "überlizenziert")
        self.assertEqual(license_status(True, 8, 8), "ausgeglichen")

    def test_per_user_counts_devices_without_user_once(self):
        models = {"m": {"product": "P", "publisher": "X", "metric": PER_USER}}
        inst = [{"model": "m", "device": "d1", "user": "u1"}, {"model": "m", "device": "d2", "user": "u1"},
                {"model": "m", "device": "d3", "user": ""}, {"model": "m", "device": "d4", "user": ""}]
        self.assertEqual(compute_position(inst, [], models)[0]["usage"], 3)
        models["m"]["metric"] = PER_DEVICE
        self.assertEqual(compute_position(inst, [], models)[0]["usage"], 4)

    def test_compare_reports_deviations(self):
        expected = expected_rows(DATA["ground_truth"])
        rows = [dict(r) for r in expected]
        rows[0]["usage"] += 1
        result = compare(rows[1:] + [rows[0], {**rows[0], "product": "Extra"}], expected)
        self.assertTrue(result[expected[0]["product"]])
        self.assertEqual(result["Extra"], ["nicht erwartet"])


class ScriptInclude(unittest.TestCase):
    """Das Script Include in ServiceNow muss dieselben Regeln haben wie die Prüfung."""

    def test_same_status_values(self):
        for status in STATUS_EN:
            self.assertIn(f"'{status}'", SCRIPT)

    def test_same_license_types(self):
        for license_type in (PER_USER, PER_DEVICE):
            self.assertIn(f"'{license_type}'", SCRIPT)
        utils = (ROOT / "servicenow" / "sam_import_utils.js").read_text(encoding="utf-8")
        for metric, license_type in METRIC.items():
            self.assertIn(f"'{metric}': '{license_type}'", utils)


if __name__ == "__main__":
    unittest.main()
