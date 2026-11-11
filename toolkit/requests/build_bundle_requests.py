#!/usr/bin/env python3
"""Deploy bundle of ITAM Toolkit 0.2.0: two catalog items with Flow Designer flows.

«Gerät zurückgeben oder tauschen» (return or exchange a device) and «Asset-Daten oder Standort
ändern» (change asset data or location). Same format and placeholders as build_bundle.py; the
deployer in deploy_in_browser.js upserts the records. The flows and the custom action
«ITAM Toolkit: run request step» are built in Flow Designer (see docs/catalog.md) and versioned
with the update set export.

Usage:  python3 toolkit/requests/build_bundle_requests.py [--out bundle_requests.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_bundle import GLOBAL, RUN_SERVER_SCRIPT, VAR_JASMINE, VAR_SCRIPT  # noqa: E402

HERE = Path(__file__).resolve().parent


def src(name: str) -> str:
    text = (HERE / name).read_text(encoding="utf-8")
    if "{{" in text:
        raise SystemExit(f"{name} contains '{{{{', which the deployer would treat as a placeholder")
    return text


def atf_script(name: str) -> str:
    """ATF test script with the shared helpers pasted in at the marker (a step script cannot import)."""
    return src(name).replace(
        "    // @helpers", "\n".join("    " + line if line else line for line in src("atf_helpers.js").splitlines())
    )


RETURN_ITEM = "Gerät zurückgeben oder tauschen"
CHANGE_ITEM = "Asset-Daten oder Standort ändern"

# (name, label, type, order, extra); types: 8 reference, 5 select box, 6 single line, 2 multi line
RETURN_VARIABLES = [
    (
        "requested_for",
        "Für wen?",
        "8",
        100,
        {"reference": "sys_user", "mandatory": "true", "default_value": "javascript:gs.getUserID()"},
    ),
    (
        "device",
        "Gerät",
        "8",
        200,
        {
            "reference": "alm_hardware",
            "mandatory": "true",
            "use_reference_qualifier": "advanced",
            "reference_qual": "javascript:'assigned_to=' + current.variables.requested_for"
            " + '^install_statusNOT IN6,7,8'",
            "attributes": "ref_qual_elements=requested_for",
        },
    ),
    ("reason", "Grund", "5", 300, {"mandatory": "true"}),
    ("comment", "Bemerkung", "2", 400, {}),
]
RETURN_CHOICES = [
    ("defekt", "Defekt"),
    ("tausch", "Tausch (anderes oder neues Gerät)"),
    ("nicht_benoetigt", "Nicht mehr benötigt"),
]

CHANGE_VARIABLES = [
    (
        "asset",
        "Asset",
        "8",
        100,
        {
            "reference": "alm_hardware",
            "mandatory": "true",
            "use_reference_qualifier": "advanced",
            "reference_qual": "install_statusNOT IN7,8",
        },
    ),
    ("change_type", "Was soll geändert werden?", "5", 200, {"mandatory": "true"}),
    ("new_location", "Neuer Standort", "8", 300, {"reference": "cmn_location"}),
    ("new_cost_center", "Neue Kostenstelle", "8", 400, {"reference": "cmn_cost_center"}),
    ("new_assigned_to", "Neu zugeordnet an", "8", 500, {"reference": "sys_user"}),
    ("justification", "Begründung", "2", 600, {"mandatory": "true"}),
]
CHANGE_CHOICES = [("standort", "Standort"), ("kostenstelle", "Kostenstelle"), ("zuordnung", "Zuordnung (Benutzer)")]
# change type -> the one variable that is shown and mandatory for it
CHANGE_POLICIES = {"standort": "new_location", "kostenstelle": "new_cost_center", "zuordnung": "new_assigned_to"}

PRIVILEGES = [
    ("sc_req_item", "read,write", "requested item of both flows, closed with the result"),
    ("sc_cat_item", "read", "which catalog item a request belongs to"),
    ("sys_user_group", "read", "fallback approval group"),
    ("sysapproval_approver", "read,write", "rejection comment; ATF approves and rejects"),
    ("cmn_location", "read", "new location"),
    ("cmn_cost_center", "read", "new cost center"),
    ("cmn_department", "read", "head of the asset's department (approver)"),
    ("alm_asset", "write", "asset fields of a data change"),
    ("sys_hub_flow", "read", "ATF only: flow published and bound to the item"),
    ("sc_item_option", "create", "ATF only: variables of a test request"),
    ("sc_item_option_mtom", "create", "ATF only: variables of a test request"),
    ("sc_req_item", "create", "ATF only: test request"),
    ("cmn_department", "create", "ATF only: department with a head"),
    ("cmn_location", "create", "ATF only: target location of a change"),
    ("item_option_new", "read", "ATF only: variable definitions"),
    ("sys_flow_context", "read", "ATF only: waiting flow context after the approval"),
]


def build() -> list[dict]:
    recs: list[dict] = []

    def add(table: str, match: dict, values: dict | None = None, key: str | None = None):
        recs.append({"table": table, "match": match, "values": values or {}, "key": key, "required": True})

    add(
        "sys_script_include",
        {"name": "ItamKitRequests", "sys_scope": "{{APP}}"},
        {
            "api_name": "{{P}}.ItamKitRequests",
            "script": src("ItamKitRequests.js"),
            "description": "Scripted steps of the catalog flows «Gerät zurückgeben oder tauschen» and "
            "«Asset-Daten oder Standort ändern»",
            "access": "package_private",
            "active": "true",
            "client_callable": "false",
        },
    )
    add(
        "sys_properties",
        {"name": "{{P}}.requests.fallback_group"},
        {
            "value": "",
            "type": "string",
            "description": "Name of the group that approves when no manager, asset owner or department head is found.",
        },
    )
    add(
        "sys_choice",
        {"name": "{{P}}_audit_log", "element": "module", "value": "request", "language": "en"},
        {"label": "Catalog request", "sequence": "40", "inactive": "false"},
    )

    for target, ops, _why in PRIVILEGES:
        for op in ops.split(","):
            add(
                "sys_scope_privilege",
                {
                    "source_scope": "{{APP}}",
                    "target_scope": GLOBAL,
                    "target_name": target,
                    "target_type": "sys_db_object",
                    "operation": op,
                },
                {"status": "allowed"},
            )

    items = [
        (
            "item_return",
            RETURN_ITEM,
            "Return or exchange a device assigned to you; after the approval IT asset management takes it back.",
            "<p>Ein zugewiesenes Gerät zurückgeben oder tauschen. Nach der Freigabe durch die vorgesetzte Person "
            "(oder die IT-Asset-Gruppe) erhält das IT-Asset-Management eine Rückgabe-Aufgabe, bei Defekt oder Tausch "
            "zusätzlich eine Ersatz-Aufgabe.</p>",
            RETURN_VARIABLES,
            {"reason": RETURN_CHOICES},
        ),
        (
            "item_change",
            CHANGE_ITEM,
            "Request a change of location, cost center or assignment of an asset; the asset owner approves.",
            "<p>Standort, Kostenstelle oder Zuordnung eines Assets ändern. Nach der Freigabe durch den "
            "Fachbereich bzw. die Asset-Verantwortlichen wird die Änderung auf Asset und CI geschrieben und "
            "protokolliert; bei Ablehnung "
            "bleibt alles, wie es ist.</p>",
            CHANGE_VARIABLES,
            {"change_type": CHANGE_CHOICES},
        ),
    ]
    for key, name, short, description, variables, choices in items:
        add(
            "sc_cat_item",
            {"name": name, "sys_scope": "{{APP}}"},
            {
                "short_description": short,
                "description": description,
                "active": "true",
                "sc_catalogs": "{{lookup:sc_catalog:title=Service Catalog}}",
                "category": "{{lookup:sc_category:title=Hardware^sc_catalog.title=Service Catalog}}",
                "no_quantity": "true",
                "no_cart": "true",
            },
            key=key,
        )
        for name_, label, vtype, order, extra in variables:
            add(
                "item_option_new",
                {"cat_item": "{{ref:" + key + "}}", "name": name_},
                {"question_text": label, "type": vtype, "order": str(order), "active": "true", **extra},
                key=f"{key}_{name_}",
            )
            for seq, (value, text) in enumerate(choices.get(name_, []), start=1):
                add(
                    "question_choice",
                    {"question": "{{ref:" + f"{key}_{name_}" + "}}", "value": value},
                    {"text": text, "order": str(seq * 100)},
                )

    # Change item: show the matching field only for the chosen change type, mandatory there
    for change_type, variable in CHANGE_POLICIES.items():
        policy_key = f"policy_{change_type}"
        add(
            "catalog_ui_policy",
            {"catalog_item": "{{ref:item_change}}", "short_description": f"Show {variable}"},
            {
                "catalog_conditions": "IO:{{ref:item_change_change_type}}=" + change_type + "^EQ",
                "on_load": "true",
                "reverse_if_false": "true",
                "active": "true",
                "applies_to": "item",
                "applies_catalog": "true",
            },
            key=policy_key,
        )
        # On the PDI the Table API inserted these records without ui_policy and catalog_variable; both were
        # then set with a background script (GlideRecord.setValue). The update set XML holds the final records.
        add(
            "catalog_ui_policy_action",
            {"ui_policy": "{{ref:" + policy_key + "}}", "catalog_variable": "IO:{{ref:item_change_" + variable + "}}"},
            {"visible": "true", "mandatory": "true", "catalog_item": "{{ref:item_change}}"},
        )

    for key, name, file, desc in (
        (
            "atf_return",
            "ITAM Toolkit: Gerät zurückgeben oder tauschen",
            "atf_return.js",
            "Flow «Gerät zurückgeben oder tauschen»: approval routing in the flow, return with replacement, rejection",
        ),
        (
            "atf_change",
            "ITAM Toolkit: Asset-Daten oder Standort ändern",
            "atf_change.js",
            "Flow «Asset-Daten oder Standort ändern»: approval routing in the flow, change on asset and CI, rejection",
        ),
    ):
        add("sys_atf_test", {"name": name}, {"description": desc, "active": "true"}, key=key)
        add(
            "sys_atf_step",
            {"test": "{{ref:" + key + "}}", "order": "1"},
            {"step_config": RUN_SERVER_SCRIPT, "active": "true", "description": "Run Server Side Validation Script"},
            key=key + "_step",
        )
        add(
            "sys_variable_value",
            {"document": "sys_atf_step", "document_key": "{{ref:" + key + "_step}}", "variable": VAR_JASMINE},
            {"value": "3.1", "order": "100"},
        )
        add(
            "sys_variable_value",
            {"document": "sys_atf_step", "document_key": "{{ref:" + key + "_step}}", "variable": VAR_SCRIPT},
            {"value": atf_script(file), "order": "200"},
        )
    return recs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="bundle_requests.json")
    args = parser.parse_args()
    recs = build()
    Path(args.out).write_text(
        json.dumps({"records": recs, "layouts": {"forms": {}, "lists": []}}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"{len(recs)} records -> {args.out}")


if __name__ == "__main__":
    main()
