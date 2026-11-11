"""Static checks of the ITAM Toolkit sources (toolkit/), runnable without an instance."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLKIT = ROOT / "toolkit"
sys.path.insert(0, str(TOOLKIT))

import build_bundle  # noqa: E402


def sources() -> list[Path]:
    return sorted(TOOLKIT.rglob("*.js"))


def test_bundle_builds_and_only_uses_known_placeholders():
    records = build_bundle.build()
    assert len(records) > 150
    text = json.dumps(records)
    placeholders = set(re.findall(r"\{\{([a-z]+)(?::[^}]*)?\}\}", text, flags=re.I))
    assert placeholders <= {"P", "APP", "ref", "lookup"}
    keys = [r["key"] for r in records if r["key"]]
    assert len(keys) == len(set(keys))
    for ref in re.findall(r"\{\{ref:([^}]+)\}\}", text):
        assert ref in keys, ref


def test_sources_never_hard_code_the_vendor_prefix():
    for path in sources() + [TOOLKIT / "build_bundle.py"]:
        assert not re.search(r"x_\d{4,}_", path.read_text(encoding="utf-8")), path


def test_every_script_include_defines_its_class():
    for path in (TOOLKIT / "script_includes").glob("*.js"):
        text = path.read_text(encoding="utf-8")
        assert f"var {path.stem} = Class.create();" in text, path
        assert f"type: '{path.stem}'" in text, path


def test_every_script_include_is_in_the_bundle():
    names = {name for name, _ in build_bundle.SCRIPT_INCLUDES}
    assert names == {p.stem for p in (TOOLKIT / "script_includes").glob("*.js")}


def test_rest_resources_use_the_contract_and_a_role():
    for path in (TOOLKIT / "rest").glob("*.js"):
        text = path.read_text(encoding="utf-8")
        assert re.search(r"ItamKitRest\.handle\(request, response, '(user|admin)'", text), path
    assert "ItamKitRest.send" in (TOOLKIT / "script_includes" / "ItamKitRest.js").read_text(encoding="utf-8")


def test_public_methods_return_the_contract():
    """Each entry point of the three modules returns ItamKitResult (success, status_code, message)."""
    entry_points = {
        "LeaverAssetResolver": [
            "resolve",
            "prepareReportedCase",
            "syncTasks",
            "completeReturn",
            "sweep",
            "sendDueReminders",
            "kpis",
        ],
        "AssetCiDrift": ["count", "scan", "fix"],
        "DqScorecard": ["run", "latest"],
    }
    for cls, methods in entry_points.items():
        text = (TOOLKIT / "script_includes" / f"{cls}.js").read_text(encoding="utf-8")
        for method in methods:
            body = re.search(rf"\n    {method}: function \(.*?\n    \}},?\n", text, flags=re.S)
            assert body, f"{cls}.{method} not found"
            assert "ItamKitResult." in body.group(0), f"{cls}.{method} does not return ItamKitResult"


def test_atf_scripts_run_jasmine():
    for path in (TOOLKIT / "atf").glob("*.js"):
        text = path.read_text(encoding="utf-8")
        assert text.rstrip().endswith("jasmine.getEnv().execute();"), path
        assert "describe(" in text and "expect(" in text, path


SEED = (TOOLKIT / "fix_scripts" / "seed_dq_rules.js").read_text(encoding="utf-8")
JS_STRING = r"'((?:[^'\\]|\\.)*)'"


def rule_rows() -> list[list[str]]:
    """Rows of the RULES array in the fix script: code, group, dimension, weight, table, type, population, defect,
    field, compare, name, remediation."""
    rows = []
    for line in re.findall(r"^\s*\['[A-Z]\d{2}'.*?(?=^\s*\['[A-Z]\d{2}'|^\s*\];)", SEED, flags=re.S | re.M):
        line = line.replace("END_USER + '", "'sys_class_nameINcmdb_ci_computer,cmdb_ci_hardware")
        values = re.findall(JS_STRING + r"|(\d+)(?=,)", line)
        rows.append([a or b for a, b in values])
    return rows


RULE_ROWS = rule_rows()


def test_fifteen_generic_rules_with_unique_codes():
    assert len(RULE_ROWS) == 15
    codes = [r[0] for r in RULE_ROWS]
    assert len(set(codes)) == 15
    assert "muster" not in SEED.lower()


def test_rule_tables_are_covered_by_cross_scope_read_privileges():
    readable = {t for t, ops, _ in build_bundle.PRIVILEGES if "read" in ops.split(",")}
    references = {"assigned_to": "sys_user", "model_id": "cmdb_model", "manager": "sys_user", "company": "core_company"}
    for row in RULE_ROWS:
        table = row[4]
        assert table in readable, f"{row[0]}: no read privilege on {table}"
        for path in (row[7], row[9]):
            first = path.split(".")[0] if "." in path else ""
            if first:
                assert references[first] in readable, f"{row[0]}: dot-walk {path} needs read on {references[first]}"


def test_outcomes_match_the_ootb_asset_states():
    text = (TOOLKIT / "script_includes" / "LeaverAssetResolver.js").read_text(encoding="utf-8")
    outcomes = dict(re.findall(r"(\w+): \{state: '(\d+)', substatus: '\w+'", text))
    # In stock = 6, Missing = 8 (alm_asset.install_status, checked on the instance)
    assert outcomes == {"in_stock": "6", "pending_repair": "6", "pending_disposal": "6", "missing_lost": "8"}
