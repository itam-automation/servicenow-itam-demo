"""Tests of the independent DQ scorecard evaluator (loader/check_dq_scorecard.py), offline."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "loader"))

import check_dq_scorecard as dq  # noqa: E402


def rule(**kw) -> dict:
    base = {
        "code": "T01",
        "rule_type": "query",
        "population_query": "",
        "defect_query": "",
        "field": "",
        "compare_field": "",
        "company_field": "company",
        "weight": 1,
    }
    return {**base, **kw}


def test_or_binds_tighter_than_and():
    groups = dq.parse_query("install_status=1^assigned_toISEMPTY^ORassigned_to.active=false")
    assert groups == [
        [("install_status", "=", "1")],
        [("assigned_to", "ISEMPTY", ""), ("assigned_to.active", "=", "false")],
    ]


def test_longest_operator_wins():
    assert dq.parse_query("install_statusNOT IN6,7,8") == [[("install_status", "NOT IN", "6,7,8")]]
    assert dq.parse_query("assigned_toISNOTEMPTY") == [[("assigned_to", "ISNOTEMPTY", "")]]
    assert dq.parse_query("name!=x") == [[("name", "!=", "x")]]


def test_unsupported_queries_are_rejected_not_ignored():
    with pytest.raises(ValueError):
        dq.parse_query("install_status=1^NQactive=true")
    with pytest.raises(ValueError):
        dq.parse_query("warranty_expiration<javascript:gs.beginningOfToday()")


def test_query_rule_counts_population_and_defects():
    records = [
        {"name": "a", "install_status": "1", "assigned_to": "", "assigned_to.active": ""},
        {"name": "b", "install_status": "1", "assigned_to": "u1", "assigned_to.active": "false"},
        {"name": "c", "install_status": "1", "assigned_to": "u2", "assigned_to.active": "true"},
        {"name": "d", "install_status": "7", "assigned_to": "u3", "assigned_to.active": "false"},
    ]
    result = dq.evaluate(
        rule(population_query="install_statusIN1,3^assigned_toISNOTEMPTY", defect_query="assigned_to.active=false"),
        records,
    )
    assert (result["population"], result["defects"]) == (2, 1)
    assert result["score"] == 50
    assert [r["name"] for r in result["flagged"]] == ["b"]


def test_duplicates_count_surplus_records_case_insensitive():
    records = [
        {"name": n, "serial_number": s}
        for n, s in [("a", "SN1"), ("b", "sn1"), ("c", "SN1 "), ("d", "SN2"), ("e", ""), ("f", "")]
    ]
    result = dq.evaluate(rule(rule_type="duplicate", field="serial_number"), records)
    assert result["population"] == 6
    assert result["defects"] == 2  # three records share SN1; empty values are not duplicates


def test_field_mismatch_needs_both_values():
    records = [
        {"name": "a", "manufacturer": "m1", "model_id.manufacturer": "m1"},
        {"name": "b", "manufacturer": "m2", "model_id.manufacturer": "m1"},
        {"name": "c", "manufacturer": "", "model_id.manufacturer": "m1"},
    ]
    result = dq.evaluate(
        rule(rule_type="field_mismatch", field="manufacturer", compare_field="model_id.manufacturer"), records
    )
    assert result["defects"] == 1


def test_drift_uses_the_mapping_with_substatus_fallback():
    to_ci = {
        "1|": {"ci": "1"},
        "6|available": {"ci": "6"},
        "6|pending_repair": {"ci": "5"},
        "6|": {"ci": "6"},
        "10|": {"ci": ""},
    }
    records = [
        {"name": "ok", "ci": "c1", "install_status": "1", "substatus": "", "ci.install_status": "1"},
        {"name": "drift", "ci": "c2", "install_status": "6", "substatus": "pending_repair", "ci.install_status": "6"},
        {"name": "fallback", "ci": "c3", "install_status": "6", "substatus": "on_hold", "ci.install_status": "1"},
        {"name": "no expectation", "ci": "c4", "install_status": "10", "substatus": "", "ci.install_status": "7"},
        {"name": "no ci", "ci": "", "install_status": "1", "substatus": "", "ci.install_status": ""},
    ]
    result = dq.evaluate(rule(rule_type="drift"), records, to_ci)
    assert result["population"] == 4
    assert sorted(r["name"] for r in result["flagged"]) == ["drift", "fallback"]


def test_weighted_score_skips_rules_without_population():
    assert dq.weighted_score([(3, 100.0), (1, 0.0), (2, None)]) == 75.0
    assert dq.weighted_score([(1, None)]) is None


def test_baseline_snapshot_is_reproduced_by_the_weights():
    """The saved baseline snapshot: its score equals the weighted mean of its own rule scores."""
    saved = json.loads((ROOT / "docs" / "evidence" / "dq_snapshot_baseline.json").read_text(encoding="utf-8"))
    card = saved["scorecard"]
    rows = [(r["weight"], 100 * (1 - r["defects"] / r["population"])) for r in card["results"] if r["population"]]
    assert dq.weighted_score(rows) == card["score"]
    assert len(card["results"]) == 15


def test_toolkit_api_is_derived_from_the_namespace():
    assert dq.toolkit_api({"SN_ITAM_API": "/api/123456/itam_demo"}) == "/api/x_123456_itamkit/toolkit"
    assert dq.toolkit_api({"SN_TOOLKIT_API": "/api/x_1_itamkit/toolkit/"}) == "/api/x_1_itamkit/toolkit"
