"""Tests der Leitplanken des KI-Assistenten (ohne Netzwerk, ohne Modell)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "assistant"))

from readonly import ALLOWED, MAX_ROWS, SCOPE, GuardrailError, ReadOnlyClient, check_fields, check_query  # noqa: E402
from tools import TOOLS, run_tool  # noqa: E402


class FakeSN:
    """Steht für SNClient und merkt sich jede Anfrage."""

    user = "test"

    def __init__(self):
        self.requests: list[tuple[str, str, dict]] = []

    def request(self, method, path, params=None, body=None):
        self.requests.append((method, path, params or {}))
        if "/stats/" in path:
            if "sysparm_group_by" in (params or {}):
                return {"result": [{"groupby_fields": [{"value": "6", "display_value": "In stock"}],
                                    "stats": {"count": "3"}}]}
            return {"result": {"stats": {"count": "7"}}}
        if path.endswith("/license_position"):
            return {"result": {"company": "Muster AG", "positions": []}}
        return {"result": [{"name": "NBZH0001"}]}


def client() -> tuple[ReadOnlyClient, FakeSN]:
    fake = FakeSN()
    return ReadOnlyClient(fake, "/api/x/itam_demo"), fake


class ReadOnly(unittest.TestCase):
    def test_client_has_no_write_methods(self):
        for name in ("create", "update", "delete", "patch", "post", "put", "request"):
            self.assertFalse(hasattr(ReadOnlyClient, name), name)

    def test_every_tool_sends_only_get(self):
        ro, fake = client()
        run_tool(ro, "search_records", {"table": "alm_hardware", "query": "install_status=6", "fields": [],
                                        "limit": 5})
        run_tool(ro, "count_records", {"table": "cmdb_ci_hardware", "query": "", "group_by": "install_status"})
        run_tool(ro, "get_license_position", {})
        self.assertEqual(len(fake.requests), 3)
        self.assertEqual({m for m, _, _ in fake.requests}, {"GET"})

    def test_company_scope_is_always_prepended(self):
        ro, fake = client()
        ro.query("cmdb_ci_hardware", "install_status=6")
        query = fake.requests[0][2]["sysparm_query"]
        self.assertEqual(query, "company.name=Muster AG^install_status=6")
        for table in ALLOWED:
            self.assertTrue(check_query(table, "").startswith(SCOPE[table]), table)

    def test_limit_is_capped(self):
        ro, fake = client()
        ro.query("sys_user", "", [], limit=10_000)
        self.assertEqual(fake.requests[0][2]["sysparm_limit"], MAX_ROWS)


class Guardrails(unittest.TestCase):
    def assertBlocked(self, table, query):
        with self.assertRaises(GuardrailError, msg=query):
            check_query(table, query)

    def test_server_side_script_is_blocked(self):
        self.assertBlocked("cmdb_ci_hardware", "assigned_to=javascript:gs.getUserID()")
        self.assertBlocked("cmdb_ci_hardware", "nameLIKEglide")

    def test_scope_cannot_be_bypassed(self):
        self.assertBlocked("cmdb_ci_hardware", "install_status=6^NQinstall_status=1")
        self.assertBlocked("cmdb_ci_hardware", "ORinstall_status=1")
        self.assertBlocked("sys_user", "RLQUERYsys_user_has_role.user,>=1^ENDRLQUERY")

    def test_unknown_fields_are_blocked(self):
        """ServiceNow würde ein unbekanntes Feld ignorieren und zu viele Datensätze liefern."""
        self.assertBlocked("cmdb_ci_hardware", "install_statuss=6")
        self.assertBlocked("cmdb_ci_hardware", "ORDERBYfoo")
        self.assertBlocked("sys_user", "email=anna@muster.example")
        with self.assertRaises(GuardrailError):
            check_fields("sys_user", ["email"])

    def test_tables_outside_the_list_are_blocked(self):
        for table in ("sys_user_has_role", "sys_properties", "u_itam_license_position", "sys_script"):
            with self.assertRaises(GuardrailError):
                check_query(table, "")

    def test_valid_queries_pass(self):
        ok = [
            ("cmdb_ci_hardware", "install_status=6^model_id.nameLIKEThinkPad^ORDERBYname"),
            ("cmdb_ci_hardware", "warranty_expiration<2027-01-01^ORwarranty_expirationISEMPTY"),
            ("alm_hardware", "assigned_to.user_name=anna.meier^ORDERBYDESCassigned"),
            ("cmdb_software_instance", "software.model_id.nameSTARTSWITHAcrobat"),
            ("alm_license", "rights>10"),
            ("sys_user", "active=false"),
        ]
        for table, query in ok:
            self.assertEqual(check_query(table, query), f"{SCOPE[table]}^{query}")

    def test_blocked_request_never_reaches_servicenow(self):
        ro, fake = client()
        text, is_error = run_tool(ro, "search_records", {"table": "cmdb_ci_hardware",
                                                         "query": "name=x^NQname=y", "fields": [], "limit": 5})
        self.assertTrue(is_error)
        self.assertIn("Leitplanke", text)
        self.assertEqual(fake.requests, [])


class ToolDefinitions(unittest.TestCase):
    def test_strict_schemas(self):
        for tool in TOOLS:
            schema = tool["input_schema"]
            self.assertTrue(tool["strict"], tool["name"])
            self.assertFalse(schema["additionalProperties"], tool["name"])
            self.assertEqual(set(schema["required"]), set(schema["properties"]), tool["name"])

    def test_tables_in_schema_match_allowed(self):
        for tool in TOOLS:
            table = tool["input_schema"]["properties"].get("table")
            if table:
                self.assertEqual(set(table["enum"]), set(ALLOWED))

    def test_results_are_json(self):
        ro, _ = client()
        text, is_error = run_tool(ro, "count_records", {"table": "alm_hardware", "query": "", "group_by": None})
        self.assertFalse(is_error)
        self.assertEqual(json.loads(text), {"count": 7})


if __name__ == "__main__":
    unittest.main()
