"""Tests für die Abbildung der Testdaten auf ServiceNow (ohne Netzwerk)."""

from __future__ import annotations

import csv
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "loader"))
sys.path.insert(0, str(ROOT / "testdata"))

import generate_testdata as gen  # noqa: E402
from mapping import (  # noqa: E402
    COMPUTER_FIELDS,
    DATA_SOURCES,
    INSTALL_STATUS,
    References,
    build_ire_item,
    model_category,
    parse_ire_response,
)

DATA = gen.generate()
DEVICES = DATA["devices"]


def full_refs() -> References:
    """Jede Referenz der Testdaten löst auf eine künstliche sys_id auf."""
    refs = References()
    refs.company[gen.COMPANY] = "c1"
    for d in DEVICES:
        refs.manufacturer[d["manufacturer"]] = "m-" + d["manufacturer"]
        refs.model[d["model_id"]] = "mo-" + d["model_id"]
    refs.user.update({u["user_name"]: "u-" + u["user_name"] for u in DATA["users"]})
    refs.location.update({loc["name"]: "l-" + loc["name"] for loc in DATA["locations"]})
    refs.department.update({dep["name"]: "d-" + dep["name"] for dep in DATA["departments"]})
    return refs


def as_csv_row(device: dict) -> dict:
    """Werte so, wie csv.DictReader sie liefert (alles Text)."""
    return {k: "" if v is None else str(v) for k, v in device.items()}


class Mapping(unittest.TestCase):
    def test_every_status_and_source_is_mapped(self):
        for d in DEVICES:
            self.assertIn(d["install_status"], INSTALL_STATUS)
            self.assertIn(d["source"], DATA_SOURCES)

    def test_every_category_has_model_category(self):
        for m in gen.MODELS:
            self.assertTrue(model_category(m.category, m.manufacturer))

    def test_all_references_resolve_with_complete_refs(self):
        refs = full_refs()
        for d in DEVICES:
            item, missing = build_ire_item(as_csv_row(d), refs)
            self.assertEqual(missing, [], d["source_id"])
            self.assertEqual(item["className"], d["sn_class"])

    def test_empty_values_are_not_sent(self):
        """Leere Felder dürfen vorhandene Werte in der CMDB nicht überschreiben."""
        refs = full_refs()
        for d in DEVICES:
            item, _ = build_ire_item(as_csv_row(d), refs)
            self.assertNotIn("", item["values"].values(), d["source_id"])
        scan = next(d for d in DEVICES if d["source"] == gen.SOURCE_SCAN and not d["serial_number"])
        item, _ = build_ire_item(as_csv_row(scan), refs)
        for field in ("serial_number", "asset_tag", "assigned_to", "location"):
            self.assertNotIn(field, item["values"])

    def test_computer_fields_only_on_computer_classes(self):
        refs = full_refs()
        phone = next(d for d in DEVICES if d["category"] == "smartphone")
        laptop = next(d for d in DEVICES if d["category"] == "laptop" and d["install_status"] == "Installed")
        phone_item, _ = build_ire_item(as_csv_row(phone), refs)
        laptop_item, _ = build_ire_item(as_csv_row(laptop), refs)
        self.assertFalse(set(COMPUTER_FIELDS) & set(phone_item["values"]))
        self.assertIn("os", laptop_item["values"])

    def test_missing_reference_is_reported_not_sent(self):
        refs = full_refs()
        refs.user.clear()
        d = next(d for d in DEVICES if d["assigned_to"])
        item, missing = build_ire_item(as_csv_row(d), refs)
        self.assertNotIn("assigned_to", item["values"])
        self.assertIn(f"assigned_to={d['assigned_to']}", missing)

    def test_source_info_and_status_value(self):
        d = next(d for d in DEVICES if d["install_status"] == "Retired")
        item, _ = build_ire_item(as_csv_row(d), full_refs())
        self.assertEqual(item["values"]["install_status"], "7")
        self.assertEqual(item["sys_object_source_info"],
                         {"source_name": "MusterInventar", "source_native_key": d["source_id"]})

    def test_serial_variant_sent_unchanged(self):
        """Die Schreibweise der Quelle bleibt erhalten, die IRE soll damit umgehen."""
        variant = next(i for i in DATA["ground_truth"]["issues"] if i["type"] == "duplicate_serial_variant")
        d = next(d for d in DEVICES if d["source_id"] == variant["source_id"])
        item, _ = build_ire_item(as_csv_row(d), full_refs())
        self.assertEqual(item["values"]["serial_number"], d["serial_number"])

    def test_written_csv_matches_generated_data(self):
        """Der Loader liest die CSV-Dateien; sie müssen zum Generator passen."""
        path = ROOT / "testdata" / "output" / "devices.csv"
        with path.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(rows, [as_csv_row(d) for d in DEVICES])


class IreResponse(unittest.TestCase):
    def test_parses_dict_and_string_result(self):
        payload = {"items": [{"className": "cmdb_ci_computer", "operation": "INSERT", "sysId": "abc",
                              "identificationAttempts": [{"identifierName": "Hardware Rule",
                                                          "attributes": ["serial_number"],
                                                          "attemptResult": "NO_MATCH"}]}]}
        for response in ({"result": payload}, {"result": __import__("json").dumps(payload)}):
            parsed = parse_ire_response(response)
            self.assertEqual(parsed[0]["operation"], "INSERT")
            self.assertEqual(parsed[0]["sys_id"], "abc")
            self.assertEqual(parsed[0]["errors"], [])

    def test_errors_are_collected(self):
        parsed = parse_ire_response({"result": {"items": [
            {"className": "cmdb_ci_computer", "operation": "NO_CHANGE", "sysId": "",
             "errors": [{"error": "MISSING_MATCHING_ATTRIBUTES", "message": "keine Identifikation"}]}]}})
        self.assertEqual(parsed[0]["errors"], ["keine Identifikation"])


if __name__ == "__main__":
    unittest.main()
