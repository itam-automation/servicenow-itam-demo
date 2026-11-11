"""Tests für die Staging-Definitionen und die Transformskripte (ohne Netzwerk)."""

from __future__ import annotations

import csv
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "loader"))
sys.path.insert(0, str(ROOT / "testdata"))

import generate_testdata as gen  # noqa: E402
from staging import (  # noqa: E402
    BY_KEY,
    DEVICE_COLUMNS,
    KEY_COLUMN,
    SCRIPT_DIR,
    SCRIPT_INCLUDES,
    STAGING,
    parse_staging_row,
    payload,
    read_fields,
    spec,
)

DATA = gen.generate()


def csv_header(key: str) -> list[str]:
    with (ROOT / "testdata" / "output" / f"{key}.csv").open(encoding="utf-8", newline="") as f:
        return next(csv.reader(f))


class Definitions(unittest.TestCase):
    def test_columns_match_csv_files(self):
        """Jede CSV-Spalte landet in der Staging-Tabelle, keine fehlt, keine ist zu viel."""
        for s in STAGING:
            self.assertEqual(list(s.columns), csv_header(s.key), s.key)

    def test_field_maps_use_staging_columns(self):
        for s in STAGING:
            for f in s.fields:
                self.assertIn(f.source, s.columns, f"{s.key}: {f.source}")
                self.assertIn(f.choice_action, ("create", "ignore", "reject"))

    def test_master_data_has_coalesce_on_key(self):
        """Ohne Coalesce würde jeder Lauf Dubletten der Stammdaten erzeugen."""
        for s in STAGING:
            if s.key == "devices":
                continue
            coalesce = [f.source for f in s.fields if f.coalesce]
            self.assertIn(KEY_COLUMN[s.key], coalesce, s.key)

    def test_names_fit_servicenow_limits(self):
        for s in STAGING:
            self.assertTrue(s.table.startswith("u_") and len(s.table) <= 80, s.table)
            for column in (*s.columns, *s.result_columns):
                self.assertLessEqual(len(f"u_{column}"), 40, column)

    def test_referenced_scripts_exist(self):
        for s in STAGING:
            names = [f.source_script for f in s.fields] + [s.onbefore_script, s.onafter_script, s.oncomplete_script]
            for name in filter(None, names):
                self.assertTrue((SCRIPT_DIR / name).exists(), name)
        devices = next(item for item in spec()["staging"] if item["key"] == "devices")
        self.assertIn("IdentificationEngine", devices["onbefore_script"])

    def test_inline_scripts_call_existing_functions(self):
        """Die Feldzuordnungen der SAM-Maps rufen nur Funktionen auf, die das Script Include hat."""
        utils = (SCRIPT_DIR / SCRIPT_INCLUDES["MusterSamImport"]).read_text(encoding="utf-8")
        calls = [f.source_code for s in STAGING for f in s.fields if "MusterSamImport" in f.source_code]
        self.assertGreaterEqual(len(calls), 6)
        for code in calls:
            function = re.search(r"new MusterSamImport\(\)\.(\w+)\(", code).group(1)
            self.assertIn(f"    {function}: function", utils, function)
            for column in re.findall(r"getValue\('u_(\w+)'\)", code):
                self.assertIn(column, next(s for s in STAGING if any(f.source_code == code for f in s.fields)).columns)

    def test_script_includes_define_their_class(self):
        for name, file in SCRIPT_INCLUDES.items():
            self.assertIn(f"var {name} = Class.create();", (SCRIPT_DIR / file).read_text(encoding="utf-8"))
        self.assertEqual(set(spec()["script_includes"]), set(SCRIPT_INCLUDES))

    def test_device_columns_match_generator(self):
        self.assertEqual(list(DEVICE_COLUMNS), list(DATA["devices"][0].keys()))


class DeviceScript(unittest.TestCase):
    """Die IRE-Logik liegt im Transformskript; diese Tests prüfen den Abgleich mit den Testdaten."""

    SCRIPT = (SCRIPT_DIR / BY_KEY["devices"].onbefore_script).read_text(encoding="utf-8")

    def test_data_sources_cover_generator_sources(self):
        for source in (gen.SOURCE_INVENTORY, gen.SOURCE_SCAN):
            self.assertIn(f"'{source}'", self.SCRIPT)
        for data_source in ("MusterInventar", "MusterNetzScan"):
            self.assertIn(f"'{data_source}'", self.SCRIPT)

    def test_status_values_cover_generated_statuses(self):
        for status in {d["install_status"] for d in DATA["devices"]}:
            self.assertIn(f"'{status}'", self.SCRIPT)

    def test_serial_numbers_are_normalized(self):
        self.assertIn(".replace(/\\s+/g, '').toUpperCase()", self.SCRIPT)

    def test_result_columns_are_written(self):
        for column in BY_KEY["devices"].result_columns:
            self.assertIn(f"'u_{column}'", self.SCRIPT)

    def test_serial_variants_normalize_to_original(self):
        """Gleiche Regel wie im Skript: Die Schreibvarianten aus der ground_truth werden wieder zum Original."""
        by_id = {d["source_id"]: d for d in DATA["devices"]}
        variants = [i for i in DATA["ground_truth"]["issues"] if i["type"] == "duplicate_serial_variant"]
        self.assertTrue(variants)
        for issue in variants:
            variant = by_id[issue["source_id"]]["serial_number"]
            original = by_id[issue["duplicate_of"]]["serial_number"]
            self.assertNotEqual(variant, original)
            self.assertEqual("".join(variant.split()).upper(), original)


class ImportCheck(unittest.TestCase):
    """Die Prüfung der Quelldaten im Transformskript, nachgebildet auf den Testdaten."""

    SCRIPT = (SCRIPT_DIR / BY_KEY["devices"].onbefore_script).read_text(encoding="utf-8")
    ISSUES = DATA["ground_truth"]["issues"]

    def test_rules_are_in_the_script(self):
        self.assertIn("dataSource == 'MusterInventar' && !val('location')", self.SCRIPT)
        self.assertIn("expected !== val('manufacturer')", self.SCRIPT)
        self.assertIn("source.setValue('u_dq_findings'", self.SCRIPT)

    def test_location_rule_hits_exactly_the_injected_issues(self):
        flagged = {d["source_id"] for d in DATA["devices"] if d["source"] == gen.SOURCE_INVENTORY and not d["location"]}
        injected = {i["source_id"] for i in self.ISSUES if i["type"] == "missing_location"}
        self.assertEqual(flagged, injected)

    def test_manufacturer_rule_hits_exactly_the_injected_issues(self):
        """Hersteller der Quelle gegen Hersteller des Modells, exakt verglichen (also auch «LENOVO»)."""
        maker = {m.name: m.manufacturer for m in gen.MODELS}
        flagged = {d["source_id"] for d in DATA["devices"]
                   if d["manufacturer"] and d["manufacturer"] != maker[d["model_id"]]}
        injected = {i["source_id"] for i in self.ISSUES if i["type"] == "manufacturer_name_variant"}
        self.assertEqual(flagged, injected)
        case_only = [i for i in self.ISSUES if i["type"] == "manufacturer_name_variant"
                     and i["detail"].split(" statt ")[0].lower() == i["detail"].split(" statt ")[1].lower()]
        self.assertEqual(len(case_only), 2)  # «LENOVO»: die Datenbank vergleicht ohne Gross-/Kleinschreibung


class Payload(unittest.TestCase):
    def test_payload_without_prefix_and_as_text(self):
        """insertMultiple ordnet über den Spaltennamen ohne u_ zu."""
        row = DATA["devices"][0]
        data = payload(row, BY_KEY["devices"])
        self.assertEqual(set(data), set(DEVICE_COLUMNS))
        self.assertTrue(all(isinstance(v, str) for v in data.values()))
        self.assertEqual(data["ram"], str(row["ram"]))

    def test_read_fields_and_parse(self):
        devices = BY_KEY["devices"]
        self.assertIn("u_ire_ci", read_fields(devices).split(","))
        parsed = parse_staging_row({
            "u_source_id": "INV-00001", "sys_import_state": "ignored", "sys_target_sys_id": "",
            "sys_import_state_comment": "IRE INSERT abc", "u_ire_operation": "INSERT", "u_ire_ci": "abc",
            "u_ire_match": "", "u_ire_missing": "",
        }, devices)
        self.assertEqual(parsed["key"], "INV-00001")
        self.assertEqual(parsed["ire_operation"], "INSERT")
        self.assertEqual(parsed["ire_ci"], "abc")
        users = parse_staging_row({"u_user_name": "anna.meier", "sys_import_state": "inserted"}, BY_KEY["users"])
        self.assertEqual((users["key"], users["status"]), ("anna.meier", "inserted"))


if __name__ == "__main__":
    unittest.main()
