"""Static checks of the catalog request flows (toolkit/requests/), runnable without an instance."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUESTS = ROOT / "toolkit" / "requests"
sys.path.insert(0, str(ROOT / "toolkit"))
sys.path.insert(0, str(REQUESTS))

import build_bundle_requests as bundle  # noqa: E402

SCRIPT = (REQUESTS / "ItamKitRequests.js").read_text(encoding="utf-8")


def js_keys(name: str) -> set[str]:
    block = re.search(r"ItamKitRequests\." + name + r" = \{(.*?)\n\};", SCRIPT, flags=re.S).group(1)
    return set(re.findall(r"^\s+(\w+):", block, flags=re.M))


def test_choices_match_the_script_include():
    assert {value for value, _ in bundle.RETURN_CHOICES} == js_keys("REASONS")
    assert {value for value, _ in bundle.CHANGE_CHOICES} == js_keys("CHANGES")
    assert set(bundle.CHANGE_POLICIES) == js_keys("CHANGES")


def test_bundle_references_resolve_and_privileges_are_unique():
    records = bundle.build()
    keys = [r["key"] for r in records if r["key"]]
    assert len(keys) == len(set(keys))
    for ref in re.findall(r"\{\{ref:([^}]+)\}\}", json.dumps(records)):
        assert ref in keys, ref
    pairs = [(target, op) for target, ops, _ in bundle.PRIVILEGES for op in ops.split(",")]
    assert len(pairs) == len(set(pairs))


def test_atf_scripts_carry_the_shared_helpers():
    for name in ("atf_return.js", "atf_change.js"):
        script = bundle.atf_script(name)
        assert "// @helpers" not in script
        assert "function runFlowToApproval" in script
        assert "waiting state" in script
        assert script.rstrip().endswith("jasmine.getEnv().execute();")
