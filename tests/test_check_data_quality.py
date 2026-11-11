"""Tests der Zuordnung im Datenqualitäts-Check (ohne Netzwerk)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "loader"))

from check_data_quality import classify, finding_codes  # noqa: E402

CI = {"name": "NB1", "serial_number": "S1", "location.name": "Muster AG Zürich", "assigned_to.user_name": "anna",
      "assigned_to.location.name": "Muster AG Zürich", "manufacturer.name": "Lenovo", "install_status": "1",
      "sys_class_name": "cmdb_ci_computer"}
GT = {"issues": [{"type": "missing_location", "source_id": "INV-1", "name": "NB1", "detail": "Standort entfernt"}]}
FOUND = {"missing_location": set(), "duplicates": set()}


class Classify(unittest.TestCase):
    def test_finding_codes(self):
        self.assertEqual(finding_codes("location_missing; manufacturer_mismatch: LENOVO (Modell: Lenovo)"),
                         ["location_missing", "manufacturer_mismatch"])
        self.assertEqual(finding_codes(""), [])

    def test_platform_fix_without_report_is_not_detected(self):
        row = classify(GT, [CI], FOUND, {})[0]
        self.assertEqual(row["detected_by"], "Platform")

    def test_import_check_reports_what_the_platform_fixed(self):
        row = classify(GT, [CI], FOUND, {}, {"INV-1": ["location_missing"]})[0]
        self.assertEqual(row["detected_by"], "Import check")
        self.assertIn("location taken over from the assigned user", row["note"])

    def test_report_takes_precedence(self):
        found = {"missing_location": {"NB1"}, "duplicates": set()}
        row = classify(GT, [CI], found, {}, {"INV-1": ["location_missing"]})[0]
        self.assertEqual(row["detected_by"], "Report")
        self.assertTrue(row["import_flagged"])

    def test_wrong_finding_does_not_count(self):
        row = classify(GT, [CI], FOUND, {}, {"INV-1": ["manufacturer_mismatch"]})[0]
        self.assertEqual(row["detected_by"], "Platform")


if __name__ == "__main__":
    unittest.main()
