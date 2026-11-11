#!/usr/bin/env python3
"""Builds the deploy bundle of the ITAM Toolkit scoped app from the sources in toolkit/.

The bundle is a JSON list of records (table, match, values). A small deployer in the
admin's browser session upserts them through the Table API into the app's scope and
update set (see toolkit/deploy_in_browser.js). Placeholders resolved by the deployer:

    {{P}}                    scope name x_<prefix>_itamkit (the sources never hard-code it)
    {{APP}}                  sys_id of the app
    {{ref:key}}              sys_id of a record created earlier in the same bundle
    {{lookup:table:query}}   sys_id of the first record matching an encoded query

Usage:  python3 toolkit/build_bundle.py [--out bundle.json] [--only key1,key2]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUN_SERVER_SCRIPT = "41de4a935332120028bc29cac2dc349a"  # ATF step config «Run Server Side Script»
VAR_SCRIPT = "989d9e235324220002c6435723dc3484"  # step input «Test script»
VAR_JASMINE = "42f2564b73031300440211d8faf6a777"  # step input «Jasmine version»
GLOBAL = "global"

CASE = "{{P}}_leaver_case"
RULE = "{{P}}_dq_rule"
CARD = "{{P}}_dq_scorecard"
SNAP = "{{P}}_dq_snapshot"
RESULT = "{{P}}_dq_result"
FINDING = "{{P}}_drift_finding"
AUDIT = "{{P}}_audit_log"
OUTCOME = "{{P}}_return_outcome"


def src(path: str) -> str:
    text = (ROOT / path).read_text(encoding="utf-8")
    if "{{" in text:
        raise SystemExit(f"{path} contains '{{{{', which the deployer would treat as a placeholder")
    return text


# --------------------------------------------------------------------------- tables
# (suffix, label, extends, columns); column = (element, label, type, extra)
TABLES = [
    (
        "leaver_case",
        "Leaver Case",
        "task",
        [
            ("leaver", "Leaver", "reference", {"reference": "sys_user", "mandatory": "true"}),
            ("last_working_day", "Last working day", "glide_date", {}),
            ("lwd_estimated", "Last working day estimated", "boolean", {"default_value": "false"}),
            ("hr_contact", "HR contact", "reference", {"reference": "sys_user"}),
            ("manager", "Manager", "reference", {"reference": "sys_user"}),
            ("private_email", "Private contact address", "email", {"max_length": "100"}),
            ("trigger_source", "Trigger", "choice", {"max_length": "40", "choice": "1"}),
            ("assets_total", "Assets", "integer", {"read_only": "true"}),
            ("assets_open", "Assets open", "integer", {"read_only": "true"}),
            ("assets_returned", "Assets returned", "integer", {"read_only": "true"}),
            ("assets_lost", "Assets missing/lost", "integer", {"read_only": "true"}),
            ("return_rate", "Return rate (%)", "decimal", {"read_only": "true"}),
            ("cycle_time_days", "Cycle time (days)", "integer", {"read_only": "true"}),
            ("reminder_level", "Last reminder (day)", "integer", {"read_only": "true", "default_value": "0"}),
            ("last_reminder", "Last reminder sent", "glide_date_time", {"read_only": "true"}),
            ("escalated", "Escalated", "boolean", {"default_value": "false", "read_only": "true"}),
        ],
    ),
    (
        "dq_scorecard",
        "DQ Scorecard",
        "",
        [
            ("name", "Name", "string", {"max_length": "100", "display": "true", "mandatory": "true"}),
            ("active", "Active", "boolean", {"default_value": "true"}),
            ("company", "Company", "reference", {"reference": "core_company"}),
            ("description", "Description", "string", {"max_length": "1000"}),
        ],
    ),
    (
        "dq_rule",
        "DQ Rule",
        "",
        [
            ("code", "Code", "string", {"max_length": "10"}),
            ("name", "Name", "string", {"max_length": "100", "display": "true", "mandatory": "true"}),
            ("active", "Active", "boolean", {"default_value": "true"}),
            ("order", "Order", "integer", {"default_value": "100"}),
            ("rule_group", "Group", "choice", {"max_length": "40", "choice": "1"}),
            ("dimension", "Dimension", "choice", {"max_length": "40", "choice": "1"}),
            ("weight", "Weight", "integer", {"default_value": "1"}),
            ("table_name", "Table", "table_name", {"max_length": "80", "mandatory": "true"}),
            ("rule_type", "Rule type", "choice", {"max_length": "40", "choice": "3", "default_value": "query"}),
            (
                "population_query",
                "Population",
                "conditions",
                {"max_length": "4000", "dependent_on_field": "table_name", "use_dependent_field": "true"},
            ),
            (
                "defect_query",
                "Defect condition",
                "conditions",
                {"max_length": "4000", "dependent_on_field": "table_name", "use_dependent_field": "true"},
            ),
            ("field", "Field (duplicate / mismatch)", "string", {"max_length": "80"}),
            ("compare_field", "Compare with field", "string", {"max_length": "80"}),
            ("company_field", "Company field", "string", {"max_length": "80", "default_value": "company"}),
            ("remediation", "Remediation hint", "string", {"max_length": "1000"}),
        ],
    ),
    (
        "dq_snapshot",
        "DQ Snapshot",
        "",
        [
            ("snapshot_label", "Snapshot", "string", {"max_length": "120", "display": "true"}),
            ("scorecard", "Scorecard", "reference", {"reference": CARD}),
            ("score", "Score", "decimal", {}),
            ("trigger", "Trigger", "choice", {"max_length": "40", "choice": "1"}),
            ("rules_evaluated", "Rules evaluated", "integer", {}),
            ("rules_invalid", "Rules invalid", "integer", {}),
            ("rules_empty", "Rules without population", "integer", {}),
            ("population_total", "Records checked", "integer", {}),
            ("defects_total", "Defects", "integer", {}),
            ("duration_ms", "Duration (ms)", "integer", {}),
        ],
    ),
    (
        "dq_result",
        "DQ Result",
        "",
        [
            ("snapshot", "Snapshot", "reference", {"reference": SNAP}),
            ("rule", "Rule", "reference", {"reference": RULE, "display": "true"}),
            ("status", "Status", "choice", {"max_length": "40", "choice": "1"}),
            ("population", "Population", "integer", {}),
            ("defects", "Defects", "integer", {}),
            ("score", "Score", "decimal", {}),
            ("weight", "Weight", "integer", {}),
            (
                "dimension",
                "Dimension",
                "choice",
                {"max_length": "40", "choice_table": RULE, "choice_field": "dimension"},
            ),
            ("rule_group", "Group", "choice", {"max_length": "40", "choice_table": RULE, "choice_field": "rule_group"}),
            ("message", "Message", "string", {"max_length": "255"}),
        ],
    ),
    (
        "drift_finding",
        "Drift Finding",
        "",
        [
            ("short_description", "Finding", "string", {"max_length": "255", "display": "true"}),
            ("state", "State", "choice", {"max_length": "40", "choice": "3", "default_value": "open"}),
            ("asset", "Asset", "reference", {"reference": "alm_hardware", "read_only": "true"}),
            ("ci", "Configuration item", "reference", {"reference": "cmdb_ci", "read_only": "true"}),
            ("company", "Company", "reference", {"reference": "core_company", "read_only": "true"}),
            (
                "asset_state",
                "Asset status",
                "choice",
                {
                    "max_length": "40",
                    "choice_table": "alm_asset",
                    "choice_field": "install_status",
                    "read_only": "true",
                },
            ),
            (
                "asset_substate",
                "Asset substatus",
                "choice",
                {"max_length": "40", "choice_table": "alm_asset", "choice_field": "substatus", "read_only": "true"},
            ),
            (
                "ci_status",
                "CI status",
                "choice",
                {"max_length": "40", "choice_table": "cmdb_ci", "choice_field": "install_status", "read_only": "true"},
            ),
            (
                "expected_ci_status",
                "Expected CI status (OOTB mapping)",
                "choice",
                {"max_length": "40", "choice_table": "cmdb_ci", "choice_field": "install_status", "read_only": "true"},
            ),
            (
                "proposed_asset_state",
                "Asset status if the CI leads",
                "choice",
                {
                    "max_length": "40",
                    "choice_table": "alm_asset",
                    "choice_field": "install_status",
                    "read_only": "true",
                },
            ),
            (
                "proposed_asset_substate",
                "Asset substatus if the CI leads",
                "choice",
                {"max_length": "40", "choice_table": "alm_asset", "choice_field": "substatus", "read_only": "true"},
            ),
            ("preview_asset_leads", "Preview: asset leads", "string", {"max_length": "400", "read_only": "true"}),
            ("preview_ci_leads", "Preview: CI leads", "string", {"max_length": "400", "read_only": "true"}),
            ("leading_side", "Leading side", "choice", {"max_length": "40", "choice": "1"}),
            ("last_seen", "Last seen", "glide_date_time", {}),
            ("fixed_by", "Fixed by", "reference", {"reference": "sys_user", "read_only": "true"}),
            ("fixed_on", "Fixed on", "glide_date_time", {"read_only": "true"}),
            ("resolution", "Resolution", "string", {"max_length": "1000", "read_only": "true"}),
        ],
    ),
    (
        "audit_log",
        "Toolkit Audit Log",
        "",
        [
            ("target_display", "Record", "string", {"max_length": "255", "display": "true"}),
            ("module", "Module", "choice", {"max_length": "40", "choice": "1"}),
            ("action", "Action", "string", {"max_length": "80"}),
            ("target_table", "Table", "string", {"max_length": "80"}),
            ("target_id", "Record sys_id", "string", {"max_length": "32"}),
            ("field", "Field", "string", {"max_length": "80"}),
            ("old_value", "Old value", "string", {"max_length": "255"}),
            ("new_value", "New value", "string", {"max_length": "255"}),
            (
                "leading_side",
                "Leading side",
                "choice",
                {"max_length": "40", "choice_table": FINDING, "choice_field": "leading_side"},
            ),
            ("finding", "Drift finding", "reference", {"reference": FINDING}),
            ("note", "Note", "string", {"max_length": "1000"}),
        ],
    ),
]

CHOICES = {
    (CASE, "trigger_source"): [
        ("record_producer", "Reported by HR (Austritt melden)"),
        ("user_deactivated", "User deactivated"),
        ("nightly_sweep", "Nightly sweep"),
        ("manual", "Manual / API"),
    ],
    (RULE, "rule_group"): [
        ("ci", "Configuration item"),
        ("asset", "Asset"),
        ("asset_ci", "Asset / CI"),
        ("user", "User"),
    ],
    (RULE, "dimension"): [
        ("completeness", "Completeness"),
        ("uniqueness", "Uniqueness"),
        ("consistency", "Consistency"),
        ("validity", "Validity"),
        ("timeliness", "Timeliness"),
    ],
    (RULE, "rule_type"): [
        ("query", "Query"),
        ("duplicate", "Duplicate values"),
        ("field_mismatch", "Field mismatch"),
        ("drift", "Asset/CI drift"),
    ],
    (SNAP, "trigger"): [("scheduled", "Scheduled"), ("manual", "Manual"), ("api", "REST API")],
    (RESULT, "status"): [("ok", "OK"), ("invalid", "Invalid rule"), ("empty", "No population")],
    (FINDING, "state"): [
        ("open", "Open"),
        ("fixed", "Fixed"),
        ("resolved", "Resolved elsewhere"),
        ("ignored", "Ignored"),
    ],
    (FINDING, "leading_side"): [("asset", "Asset leads"), ("ci", "CI leads")],
    (AUDIT, "module"): [("leaver", "Leaver asset return"), ("drift", "Asset/CI drift"), ("dq", "DQ scorecard")],
    ("asset_task", OUTCOME): [
        ("in_stock", "Returned: in stock"),
        ("pending_repair", "Returned: pending repair"),
        ("pending_disposal", "Returned: pending disposal"),
        ("missing_lost", "Missing: lost"),
    ],
}

PROPERTIES = [
    (
        "leaver.reminder_days",
        "3,7,14",
        "Days after the last working day on which reminders go out; the last one is the escalation.",
    ),
    (
        "leaver.asset_query",
        "install_statusNOT IN6,7,8",
        "Encoded query on alm_hardware: which assigned assets a leaver must return "
        "(default: not in stock, retired or missing).",
    ),
    ("leaver.assignment_group", "", "sys_id of the group that gets the leaver cases and return tasks (optional)."),
]

# Glide APIs the platform also gates under runtime access tracking «Enforcing» (verified: without them
# the ATF tests fail with CrossScopeAccessNotAllowedException).
API_PRIVILEGES = [
    ("GlideRecord.setValue", "set field values on any GlideRecord"),
    ("GlideRecord.insert", "insert records (cases, tasks, findings, snapshots)"),
    ("GlideRecord.update", "update records (case counters, asset end state, CI status, findings)"),
    ("ScopedGlideElement", "assign journal fields (work notes) and other element values"),
    ("Glide API: properties", "gs.getProperty for the toolkit properties"),
]

SCRIPT_INCLUDES = [
    ("ItamKitResult", "Output contract {success, status_code, message, data} of every building block"),
    ("ItamKitConfig", "Names of tables, properties, events and roles, derived from the running scope"),
    ("ItamKitQuery", "Validates encoded queries; ServiceNow would silently drop unknown fields"),
    ("ItamKitAudit", "Toolkit audit log for changes to records the toolkit does not own"),
    ("ItamKitRest", "Shared code of the Scripted REST API"),
    ("LeaverAssetResolver", "Module 1: leaver asset return, idempotent"),
    ("AssetCiDrift", "Module 2: asset/CI status drift against the OOTB mapping"),
    ("DqScorecard", "Module 2: weighted data quality score from the rule table"),
]

# (scope-relative table, operations, why)
PRIVILEGES = [
    ("sys_user", "read", "leaver, manager, HR contact; DQ rules on users"),
    ("alm_hardware", "read,write", "assets of the leaver, end state of a return, drift fix (CI leads)"),
    ("alm_asset", "read", "asset fields reached through references"),
    ("asset_task", "read,write,create", "return tasks"),
    ("cmdb_ci", "read,write", "CI status, drift fix (asset leads)"),
    ("cmdb_ci_hardware", "read", "DQ rules on CIs"),
    ("cmdb_model", "read", "DQ rule manufacturer vs. model manufacturer"),
    ("core_company", "read", "scorecard company"),
    ("alm_asset_ci_state_mapping", "read", "target state of the drift watcher (OOTB mapping)"),
    ("sys_choice", "read", "labels in previews"),
    ("sys_scope", "read", "app version in GET /health"),
    # ATF tests run in the app scope and create their own data (rolled back after the run)
    ("sys_user", "create,write", "ATF only: test users, deactivation"),
    ("cmdb_ci_computer", "create", "ATF only: test devices"),
    ("alm_hardware", "create", "ATF only: test assets"),
    ("core_company", "create", "ATF only: test company and manufacturers"),
    ("cmdb_hardware_product_model", "create", "ATF only: test model"),
]


# Form layouts (default view): fields in order; ".split" starts the right column, ".end_split" ends the
# two-column block, ".begin_split" starts the next one. related = related lists (table.reference_field).
FORMS = {
    CASE: {
        "fields": [
            "number",
            "leaver",
            "manager",
            "hr_contact",
            "private_email",
            "trigger_source",
            ".split",
            "state",
            "priority",
            "last_working_day",
            "lwd_estimated",
            "due_date",
            "assignment_group",
            ".end_split",
            "short_description",
            ".begin_split",
            "assets_total",
            "assets_returned",
            "assets_lost",
            "assets_open",
            ".split",
            "return_rate",
            "cycle_time_days",
            "reminder_level",
            "last_reminder",
            "escalated",
            ".end_split",
            "work_notes",
            "close_notes",
        ],
        "related": ["asset_task.parent"],
    },
    FINDING: {
        "fields": [
            "short_description",
            ".begin_split",
            "asset",
            "ci",
            "company",
            "state",
            "last_seen",
            ".split",
            "asset_state",
            "asset_substate",
            "ci_status",
            "expected_ci_status",
            ".end_split",
            "leading_side",
            "preview_asset_leads",
            "preview_ci_leads",
            ".begin_split",
            "proposed_asset_state",
            "proposed_asset_substate",
            ".split",
            "fixed_by",
            "fixed_on",
            ".end_split",
            "resolution",
        ],
        "related": [AUDIT + ".finding"],
    },
    RULE: {
        "fields": [
            "code",
            "name",
            "active",
            "order",
            "rule_group",
            ".split",
            "dimension",
            "weight",
            "rule_type",
            "table_name",
            "company_field",
            ".end_split",
            "population_query",
            "defect_query",
            "field",
            "compare_field",
            "remediation",
        ],
        "related": [],
    },
    CARD: {
        "fields": ["name", "company", ".split", "active", ".end_split", "description"],
        "related": [SNAP + ".scorecard"],
    },
    SNAP: {
        "fields": [
            "snapshot_label",
            "scorecard",
            "score",
            "trigger",
            ".split",
            "rules_evaluated",
            "rules_invalid",
            "rules_empty",
            "population_total",
            "defects_total",
            "duration_ms",
            ".end_split",
        ],
        "related": [RESULT + ".snapshot"],
    },
    RESULT: {
        "fields": [
            "rule",
            "snapshot",
            "status",
            "score",
            ".split",
            "population",
            "defects",
            "weight",
            "dimension",
            "rule_group",
            ".end_split",
            "message",
        ],
        "related": [],
    },
    AUDIT: {
        "fields": [
            "target_display",
            "module",
            "action",
            "target_table",
            "target_id",
            ".split",
            "field",
            "old_value",
            "new_value",
            "leading_side",
            "finding",
            ".end_split",
            "note",
        ],
        "related": [],
    },
}

# List layouts (default view); (table, parent table for a related list or "", columns)
LISTS = [
    (
        CASE,
        "",
        [
            "number",
            "leaver",
            "last_working_day",
            "trigger_source",
            "state",
            "assets_total",
            "assets_returned",
            "assets_lost",
            "return_rate",
            "cycle_time_days",
            "reminder_level",
            "escalated",
        ],
    ),
    # asset_task belongs to Global: a scoped app may not add list layouts to it (platform rule), so the
    # return task related list uses the asset_task default layout; the outcome column is added per user.
    (
        FINDING,
        "",
        [
            "short_description",
            "asset",
            "asset_state",
            "ci_status",
            "expected_ci_status",
            "state",
            "leading_side",
            "last_seen",
        ],
    ),
    (RULE, "", ["order", "code", "name", "rule_group", "dimension", "weight", "table_name", "rule_type", "active"]),
    (
        SNAP,
        "",
        ["snapshot_label", "scorecard", "score", "rules_evaluated", "defects_total", "trigger", "sys_created_on"],
    ),
    (RESULT, SNAP, ["rule", "status", "population", "defects", "score", "weight", "dimension"]),
    (
        AUDIT,
        "",
        [
            "sys_created_on",
            "module",
            "action",
            "target_display",
            "field",
            "old_value",
            "new_value",
            "leading_side",
            "sys_created_by",
        ],
    ),
    (AUDIT, FINDING, ["sys_created_on", "action", "target_display", "field", "old_value", "new_value", "leading_side"]),
]


REPORTS = [
    # Line over time: one point per day (the nightly snapshot); ServiceNow trends have no finer unit than an hour.
    (
        "ITAM Toolkit: DQ score trend",
        {
            "table": SNAP,
            "type": "line",
            "trend_field": "sys_created_on",
            "interval": "date",
            "aggregate": "AVG",
            "sumfield": "score",
            "field": "scorecard",
            "filter": "scorecard.active=true",
        },
    ),
    # Every snapshot as its own bar, also for several runs on one day
    (
        "ITAM Toolkit: DQ score per snapshot",
        {
            "table": SNAP,
            "type": "bar",
            "field": "snapshot_label",
            "aggregate": "AVG",
            "sumfield": "score",
            "filter": "scorecard.active=true^ORDERBYsnapshot_label",
        },
    ),
    (
        "ITAM Toolkit: leaver cases by state",
        {"table": CASE, "type": "bar", "field": "state", "aggregate": "COUNT", "filter": ""},
    ),
    (
        "ITAM Toolkit: return outcomes",
        {
            "table": "asset_task",
            "type": "pie",
            "field": OUTCOME,
            "aggregate": "COUNT",
            "filter": OUTCOME + "ISNOTEMPTY",
        },
    ),
    (
        "ITAM Toolkit: leaver cycle time (closed cases)",
        {
            "table": CASE,
            "type": "single_score",
            "aggregate": "AVG",
            "sumfield": "cycle_time_days",
            "filter": "active=false",
        },
    ),
]


def build() -> list[dict]:
    recs: list[dict] = []

    def add(table: str, match: dict, values: dict | None = None, key: str | None = None, required: bool = True):
        recs.append({"table": table, "match": match, "values": values or {}, "key": key, "required": required})

    for name, value, desc in PROPERTIES:
        add("sys_properties", {"name": "{{P}}." + name}, {"value": value, "description": desc, "type": "string"})

    for suffix, label, extends, columns in TABLES:
        table = "{{P}}_" + suffix
        values = {
            "label": label,
            "create_access_controls": "true",
            "user_role": "{{lookup:sys_user_role:name={{P}}.user}}",
            "is_extendable": "false",
        }
        if extends:
            values["super_class"] = "{{lookup:sys_db_object:name=" + extends + "}}"
        add("sys_db_object", {"name": table}, values, key="table_" + suffix)
        for element, col_label, col_type, extra in columns:
            add(
                "sys_dictionary",
                {"name": table, "element": element},
                {"column_label": col_label, "internal_type": col_type, **extra},
            )
    add("sys_number", {"category": CASE}, {"prefix": "LVR", "number": "1000", "maximum_digits": "7"})
    add(
        "sys_dictionary",
        {"name": "asset_task", "element": OUTCOME},
        {
            "column_label": "Return outcome",
            "internal_type": "choice",
            "max_length": "40",
            "choice": "1",
            "read_only": "true",
        },
    )

    for (table, element), choices in CHOICES.items():
        for seq, (value, label) in enumerate(choices, start=1):
            add(
                "sys_choice",
                {"name": table, "element": element, "value": value, "language": "en"},
                {"label": label, "sequence": str(seq * 10), "inactive": "false"},
            )

    for name, desc in SCRIPT_INCLUDES:
        add(
            "sys_script_include",
            {"name": name, "sys_scope": "{{APP}}"},
            {
                "api_name": "{{P}}." + name,
                "script": src(f"script_includes/{name}.js"),
                "description": desc,
                "access": "package_private",
                "active": "true",
                "client_callable": "false",
            },
        )

    for target, _why in API_PRIVILEGES:
        add(
            "sys_scope_privilege",
            {
                "source_scope": "{{APP}}",
                "target_scope": GLOBAL,
                "target_name": target,
                "target_type": "scriptable",
                "operation": "execute",
            },
            {"status": "allowed"},
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

    # Business rules
    add(
        "sys_script",
        {"name": "ITAM Toolkit: create return tasks", "collection": CASE},
        {
            "when": "after",
            "order": "100",
            "action_insert": "true",
            "action_update": "false",
            "advanced": "true",
            "active": "true",
            "script": src("business_rules/leaver_case_sync_tasks.js"),
            "description": "Module 1: one asset_task per hardware asset still assigned to the leaver",
        },
    )
    add(
        "sys_script",
        {"name": "ITAM Toolkit: leaver on deactivation", "collection": "sys_user"},
        {
            "when": "after",
            "order": "200",
            "action_insert": "false",
            "action_update": "true",
            "advanced": "true",
            "active": "true",
            "condition": "current.active.changesTo(false)",
            "script": src("business_rules/user_deactivated.js"),
            "description": "Module 1, trigger (b): user deactivated",
        },
    )

    # Events, mail script, notifications
    for event, desc in (
        ("leaver.reminder", "Leaver asset return reminder (parm1 recipients, parm2 day)"),
        ("leaver.escalation", "Leaver asset return escalation (parm1 recipients, parm2 day)"),
    ):
        add("sysevent_register", {"event_name": "{{P}}." + event}, {"table": CASE, "description": desc})
    add("sys_script_email", {"name": "itamkit_open_returns"}, {"script": src("mail_scripts/itamkit_open_returns.js")})
    body = (
        "<p>The following hardware of <strong>${leaver}</strong> (last working day ${last_working_day}) "
        "has not been returned yet:</p>"
        "${mail_script:itamkit_open_returns}"
        "<p>The leaver is inactive and does not receive this e-mail. Please arrange the return with the leaver.</p>"
        "<p>Case ${number}: ${URI_REF}</p>"
    )
    add(
        "sysevent_email_action",
        {"name": "ITAM Toolkit: leaver asset return reminder", "collection": CASE},
        {
            "event_name": "{{P}}.leaver.reminder",
            "generation_type": "event",
            "event_parm_1": "true",
            "active": "true",
            "subject": "${number}: hardware of ${leaver} not returned "
            "(day ${reminder_level} after the last working day)",
            "message_html": body,
            "action_insert": "false",
            "action_update": "false",
        },
    )
    add(
        "sysevent_email_action",
        {"name": "ITAM Toolkit: leaver asset return escalation", "collection": CASE},
        {
            "event_name": "{{P}}.leaver.escalation",
            "generation_type": "event",
            "event_parm_1": "true",
            "active": "true",
            "importance": "high",
            "subject": "Escalation ${number}: hardware of ${leaver} still not returned (day ${reminder_level})",
            "message_html": body.replace("<p>The following", "<p><strong>Escalation.</strong> The following"),
            "action_insert": "false",
            "action_update": "false",
        },
    )

    # Scheduled jobs (daily, instance time)
    add(
        "sysauto_script",
        {"name": "ITAM Toolkit: leaver sweep"},
        {
            "run_type": "daily",
            "run_time": "1970-01-01 01:30:00",
            "active": "true",
            "script": src("scheduled_jobs/leaver_sweep.js"),
        },
    )
    add(
        "sysauto_script",
        {"name": "ITAM Toolkit: drift scan and DQ snapshot"},
        {
            "run_type": "daily",
            "run_time": "1970-01-01 02:00:00",
            "active": "true",
            "script": src("scheduled_jobs/dq_nightly.js"),
        },
    )

    # Fix script: generic DQ rules
    add(
        "sys_script_fix",
        {"name": "ITAM Toolkit: seed generic DQ rules"},
        {
            "script": src("fix_scripts/seed_dq_rules.js"),
            "description": "15 generic DQ rules and the scorecard «All companies»; idempotent",
            "record_for_rollback": "false",
        },
    )

    # UI actions
    outcomes = [
        ("in_stock", "Returned: in stock", 100),
        ("pending_repair", "Returned: needs repair", 110),
        ("pending_disposal", "Returned: for disposal", 120),
        ("missing_lost", "Missing / lost", 130),
    ]
    for outcome, label, order in outcomes:
        add(
            "sys_ui_action",
            {"name": label, "table": "asset_task", "sys_scope": "{{APP}}"},
            {
                "action_name": "itamkit_return_" + outcome,
                "form_button": "true",
                "active": "true",
                "order": str(order),
                "condition": "current.active == true && new LeaverAssetResolver().isLeaverTask(current)",
                "script": src("ui_actions/return_outcome.js").replace("__OUTCOME__", outcome),
            },
        )
    add(
        "sys_ui_action",
        {"name": "Drift beheben", "table": FINDING},
        {
            "action_name": "itamkit_fix_drift",
            "form_button": "true",
            "active": "true",
            "order": "100",
            "client": "true",
            "onclick": "itamkitFixDrift()",
            "isolate_script": "false",
            "condition": "current.state == 'open'",
            "hint": "Preview the change of the chosen leading side, apply it and write the audit log",
            "script": src("ui_actions/fix_drift.js"),
        },
    )
    add(
        "sys_ui_action",
        {"name": "Run snapshot now", "table": CARD},
        {
            "action_name": "itamkit_run_snapshot",
            "form_button": "true",
            "active": "true",
            "order": "100",
            "script": src("ui_actions/run_snapshot.js"),
        },
    )
    add(
        "sys_ui_action",
        {"name": "Sync return tasks", "table": CASE},
        {
            "action_name": "itamkit_sync_tasks",
            "form_button": "true",
            "active": "true",
            "order": "100",
            "condition": "current.active == true",
            "script": src("ui_actions/sync_return_tasks.js"),
        },
    )

    # Scripted REST API
    add(
        "sys_ws_definition",
        {"service_id": "toolkit", "sys_scope": "{{APP}}"},
        {
            "name": "ITAM Toolkit",
            "active": "true",
            "short_description": "ITAM Toolkit: health, DQ scorecard, drift mapping, leaver KPIs",
        },
        key="rest",
    )
    for name, method, path, file in (
        ("health", "GET", "/health", "get_health"),
        ("dq scorecard", "GET", "/dq/scorecard", "get_dq_scorecard"),
        ("dq run", "POST", "/dq/run", "post_dq_run"),
        ("drift mapping", "GET", "/drift/mapping", "get_drift_mapping"),
        ("leaver kpi", "GET", "/leaver/kpi", "get_leaver_kpi"),
        ("leaver resolve", "POST", "/leaver/resolve", "post_leaver_resolve"),
    ):
        add(
            "sys_ws_operation",
            {"web_service_definition": "{{ref:rest}}", "name": name},
            {
                "http_method": method,
                "relative_path": path,
                "operation_script": src(f"rest/{file}.js"),
                "active": "true",
                "requires_authentication": "true",
                "requires_acl_authorization": "true",
                "produce_type": "application/json",
            },
        )

    # Record producer «Austritt melden»
    add(
        "sc_cat_item_producer",
        {"name": "Austritt melden"},
        {
            "table_name": CASE,
            "active": "true",
            "short_description": "Report a leaver: HR enters the last working day; "
            "IT asset management gets one return task per device.",
            "description": "<p>Austritt einer Mitarbeiterin oder eines Mitarbeiters melden. "
            "Die IT-Asset-Verwaltung erhält "
            "je zugewiesenem Gerät eine Rückgabe-Aufgabe; Erinnerungen gehen an Vorgesetzte und HR.</p>",
            "sc_catalogs": "{{lookup:sc_catalog:title=Service Catalog}}",
            "category": "{{lookup:sc_category:title=Hardware^sc_catalog.title=Service Catalog}}",
            "script": src("record_producers/austritt_melden.js"),
        },
        key="producer",
    )
    for order, (name, label, vtype, extra) in enumerate(
        (
            ("leaver", "Austretende Person", "8", {"reference": "sys_user", "mandatory": "true"}),
            ("last_working_day", "Letzter Arbeitstag", "9", {"mandatory": "true"}),
            (
                "private_email",
                "Private Kontaktadresse (optional)",
                "6",
                {"tooltip": "For reminders to the leaver after the account is deactivated"},
            ),
            ("note", "Bemerkung", "2", {}),
        ),
        start=1,
    ):
        add(
            "item_option_new",
            {"cat_item": "{{ref:producer}}", "name": name},
            {"question_text": label, "type": vtype, "order": str(order * 100), "active": "true", **extra},
        )

    # Application menu and modules
    add(
        "sys_app_application",
        {"title": "ITAM Toolkit", "sys_scope": "{{APP}}"},
        {
            "roles": "{{P}}.user",
            "active": "true",
            "order": "500",
            "hint": "Leaver asset return, asset/CI drift, DQ scorecard",
        },
        key="menu",
    )
    modules = [
        ("Leaver cases (open)", "LIST", CASE, "active=true^ORDERBYDESCopened_at", 100),
        ("All leaver cases", "LIST", CASE, "ORDERBYDESCopened_at", 110),
        ("Return tasks (open)", "LIST", "asset_task", "active=true^parent.sys_class_name=" + CASE, 120),
        ("Drift findings (open)", "LIST", FINDING, "state=open", 200),
        ("DQ scorecards", "LIST", CARD, "", 300),
        ("DQ rules", "LIST", RULE, "ORDERBYorder", 310),
        ("DQ snapshots", "LIST", SNAP, "ORDERBYDESCsys_created_on", 320),
        ("Audit log", "LIST", AUDIT, "ORDERBYDESCsys_created_on", 400),
        ("Properties", "LIST", "sys_properties", "nameSTARTSWITH{{P}}.", 500),
    ]
    for title, link, table, query, order in modules:
        add(
            "sys_app_module",
            {"title": title, "application": "{{ref:menu}}"},
            {
                "link_type": link,
                "name": table,
                "filter": query,
                "order": str(order),
                "active": "true",
                "roles": "{{P}}.user",
            },
        )

    # Reports (no Performance Analytics): trend as a line over the snapshots, leaver KPIs
    for title, values in REPORTS:
        add("sys_report", {"title": title, "sys_scope": "{{APP}}"}, values)

    # ATF tests
    for key, name, file, desc in (
        (
            "atf_leaver",
            "ITAM Toolkit: leaver asset return",
            "leaver_asset_return",
            "Module 1: triggers, end states, idempotency, reminders, escalation, KPIs",
        ),
        (
            "atf_dq",
            "ITAM Toolkit: asset/CI drift and DQ scorecard",
            "drift_and_scorecard",
            "Module 2: OOTB mapping, scan, fix with either side, audit, rule types, weighted score",
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
            {"value": src(f"atf/{file}.js"), "order": "200"},
        )
    return recs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="bundle.json")
    parser.add_argument("--only", default="", help="comma-separated tables to keep (e.g. sys_script_include)")
    args = parser.parse_args()
    recs = build()
    if args.only:
        keep = set(args.only.split(","))
        recs = [r for r in recs if r["table"] in keep]
    layouts = {"forms": FORMS, "lists": [{"table": t, "parent": p, "columns": c} for t, p, c in LISTS]}
    Path(args.out).write_text(
        json.dumps({"records": recs, "layouts": layouts}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"{len(recs)} records -> {args.out}")


if __name__ == "__main__":
    main()
