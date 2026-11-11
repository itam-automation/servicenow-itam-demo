#!/usr/bin/env python3
"""Independent check of the ITAM Toolkit DQ scorecard (module 2).

1. Reads the latest snapshot of a scorecard with its rule definitions from the
   toolkit's REST API (GET /dq/scorecard) and the OOTB asset/CI status mapping
   (GET /drift/mapping).
2. Reads the raw records through the Table API (read only) and evaluates every
   rule again in Python: its own encoded-query evaluator, duplicate and mismatch
   counting, drift against the mapping. Population, defects and the weighted
   score must equal the snapshot.
3. Cross-checks the rules that correspond to an injected error type with the
   ground truth (testdata/output/ground_truth.json): which injected issues the
   rule finds, which flagged records were not injected.

Result as Markdown in docs/dq_scorecard.md. Exit code 0 if the score matches.

Usage from the project folder:
    python3 loader/check_dq_scorecard.py [--scorecard "Muster AG"] [--snapshot snapshot.json]

--snapshot reads a saved REST answer ({"scorecard": ..., "mapping": ...}) instead of
calling the REST API, for a user without the toolkit role.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sn_client import SNClient, load_env  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
GROUND_TRUTH = ROOT / "testdata" / "output" / "ground_truth.json"
REPORT = ROOT / "docs" / "dq_scorecard.md"

# Rules of the generic rule set that correspond to an error type injected by the generator
GROUND_TRUTH_RULES = {
    "C01": "missing_serial_number",
    "C02": "missing_location",
    "C03": "duplicate_serial_variant",
    "C04": "manufacturer_name_variant",
    "C05": "installed_without_user",
    "C06": "retired_with_user",
    "C07": "assigned_to_inactive_user",
}

OPERATORS = (
    "ISNOTEMPTY",
    "ISEMPTY",
    "NOT IN",
    "NOT LIKE",
    "STARTSWITH",
    "ENDSWITH",
    "LIKE",
    "IN",
    "!=",
    ">=",
    "<=",
    "=",
    ">",
    "<",
)
TERM = re.compile(r"^([a-z0-9_.]+?)(" + "|".join(re.escape(o) for o in OPERATORS) + r")(.*)$")


# ----------------------------------------------------------------------------- encoded queries


def parse_query(query: str) -> list[list[tuple[str, str, str]]]:
    """Encoded query -> AND list of OR groups of (field, operator, value).

    ServiceNow binds ^OR tighter than ^: "a^b^ORc" means a AND (b OR c).
    """
    groups: list[list[tuple[str, str, str]]] = []
    if not query:
        return groups
    if "^NQ" in query:
        raise ValueError("^NQ is not supported")
    for and_part in re.split(r"\^(?!OR)", query):
        group = []
        for term in and_part.split("^OR"):
            if not term or term == "EQ" or term.startswith("ORDERBY"):
                continue
            match = TERM.match(term)
            if not match:
                raise ValueError(f"unsupported term {term!r}")
            if match.group(3).startswith("javascript:"):
                raise ValueError(f"javascript values are not reproducible offline: {term!r}")
            group.append(match.groups())
        if group:
            groups.append(group)
    return groups


def query_fields(query: str) -> set[str]:
    return {field for group in parse_query(query) for field, _, _ in group}


def term_matches(value: str, op: str, arg: str) -> bool:
    value = value or ""
    if op == "ISEMPTY":
        return value == ""
    if op == "ISNOTEMPTY":
        return value != ""
    if op == "=":
        return value.casefold() == arg.casefold()
    if op == "!=":
        return value.casefold() != arg.casefold()
    if op in ("IN", "NOT IN"):
        inside = value.casefold() in {a.casefold() for a in arg.split(",")}
        return inside if op == "IN" else not inside
    if op in ("LIKE", "NOT LIKE"):
        inside = arg.casefold() in value.casefold()
        return inside if op == "LIKE" else not inside
    if op == "STARTSWITH":
        return value.casefold().startswith(arg.casefold())
    if op == "ENDSWITH":
        return value.casefold().endswith(arg.casefold())
    if value == "":
        return False
    left, right = _comparable(value), _comparable(arg)
    return {"<": left < right, ">": left > right, "<=": left <= right, ">=": left >= right}[op]


def _comparable(text: str):
    try:
        return float(text)
    except ValueError:
        return text


def record_matches(record: dict, groups: list[list[tuple[str, str, str]]]) -> bool:
    return all(any(term_matches(record.get(f, ""), op, arg) for f, op, arg in group) for group in groups)


# ----------------------------------------------------------------------------- rules


def needed_fields(rule: dict) -> set[str]:
    fields = {"sys_id", "name"} | query_fields(rule["population_query"]) | query_fields(rule["defect_query"])
    if rule["rule_type"] in ("duplicate", "field_mismatch"):
        fields.add(rule["field"])
    if rule["rule_type"] == "field_mismatch":
        fields.add(rule["compare_field"])
    if rule["rule_type"] == "drift":
        fields |= {"install_status", "substatus", "ci", "ci.install_status"}
    return fields


def evaluate(rule: dict, records: list[dict], mapping: dict | None = None) -> dict:
    """Population, defects and flagged records of one rule, computed without ServiceNow."""
    population = [r for r in records if record_matches(r, parse_query(rule["population_query"]))]
    kind = rule["rule_type"]
    if kind == "query":
        defect_groups = parse_query(rule["defect_query"])
        flagged = [r for r in population if record_matches(r, defect_groups)]
        defects = len(flagged)
    elif kind == "duplicate":
        by_value: dict[str, list[dict]] = defaultdict(list)
        for r in population:
            value = (r.get(rule["field"]) or "").rstrip().casefold()
            if value:
                by_value[value].append(r)
        groups = [g for g in by_value.values() if len(g) > 1]
        defects = sum(len(g) - 1 for g in groups)
        flagged = [r for g in groups for r in g]
    elif kind == "field_mismatch":
        flagged = [
            r
            for r in population
            if r.get(rule["field"]) and r.get(rule["compare_field"]) and r[rule["field"]] != r[rule["compare_field"]]
        ]
        defects = len(flagged)
    elif kind == "drift":
        population = [r for r in population if r.get("ci")]
        flagged = [r for r in population if drifts(r, mapping or {})]
        defects = len(flagged)
    else:
        raise ValueError(f"unknown rule type {kind}")
    score = 100 * (1 - defects / len(population)) if population else None
    return {"population": len(population), "defects": defects, "score": score, "flagged": flagged}


def drifts(asset: dict, to_ci: dict) -> bool:
    state, sub = asset.get("install_status", ""), asset.get("substatus", "")
    entry = to_ci.get(f"{state}|{sub}") or to_ci.get(f"{state}|")
    expected = entry["ci"] if entry else ""
    return bool(expected) and expected != asset.get("ci.install_status", "")


def weighted_score(rows: list[tuple[int, float | None]]) -> float | None:
    valid = [(w, s) for w, s in rows if s is not None]
    if not valid:
        return None
    return round(sum(w * s for w, s in valid) / sum(w for w, _ in valid), 2)


# ----------------------------------------------------------------------------- instance


def toolkit_api(env: dict[str, str]) -> str:
    if env.get("SN_TOOLKIT_API"):
        return env["SN_TOOLKIT_API"].rstrip("/")
    match = re.match(r"/api/([^/]+)/", env.get("SN_ITAM_API", ""))
    if not match:
        raise SystemExit("Set SN_TOOLKIT_API (or SN_ITAM_API) in .env")
    return f"/api/x_{match.group(1)}_itamkit/toolkit"


def fetch_snapshot(client: SNClient, api: str, scorecard: str) -> tuple[dict, dict]:
    card = client.request("GET", api + "/dq/scorecard", {"name": scorecard})
    mapping = client.request("GET", api + "/drift/mapping")
    return card["data"], mapping["data"]["to_ci"]


def fetch_records(client: SNClient, card: dict) -> dict[str, list[dict]]:
    """Raw values of all fields the rules need, per table, limited to the scorecard's company."""
    fields: dict[str, set[str]] = defaultdict(set)
    company_field: dict[str, str] = {}
    for rule in card["results"]:
        fields[rule["table"]] |= needed_fields(rule)
        company_field[rule["table"]] = rule["company_field"]
    records = {}
    for table, names in fields.items():
        query = f"{company_field[table]}.name={card['company_name']}" if card.get("company_name") else ""
        records[table] = client.get_records(table, query, ",".join(sorted(names)))
    return records


# ----------------------------------------------------------------------------- ground truth


def ground_truth_rows(results: dict[str, dict], ground_truth: dict) -> list[dict]:
    rows = []
    for code, issue_type in GROUND_TRUTH_RULES.items():
        if code not in results:
            continue
        injected = {i["name"] for i in ground_truth["issues"] if i["type"] == issue_type}
        flagged = {r["name"] for r in results[code]["flagged"]}
        # A duplicate rule flags whole groups; the injected scan rows' partners are the original devices.
        partners = "duplicate" in issue_type
        rows.append(
            {
                "code": code,
                "type": issue_type,
                "injected": len(injected),
                "found": len(injected & flagged),
                "not_shown": sorted(injected - flagged),
                "additional": [] if partners else sorted(flagged - injected),
                "partners": sorted(flagged - injected) if partners else [],
            }
        )
    return rows


# ----------------------------------------------------------------------------- main


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scorecard", default="Muster AG")
    parser.add_argument("--snapshot", help="saved REST answer instead of the REST API")
    parser.add_argument(
        "--report", default=str(REPORT.relative_to(ROOT)), help="Markdown report, relative to the project"
    )
    args = parser.parse_args()
    report = ROOT / args.report

    client = SNClient.from_env()
    if args.snapshot:
        saved = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
        card, to_ci = saved["scorecard"], saved["mapping"]
    else:
        card, to_ci = fetch_snapshot(client, toolkit_api(load_env()), args.scorecard)
    records = fetch_records(client, card)

    lines_out, mismatches, results = [], 0, {}
    for rule in card["results"]:
        if rule["status"] != "ok":
            lines_out.append((rule, None, "skipped in ServiceNow: " + rule["status"]))
            continue
        mine = evaluate(rule, records[rule["table"]], to_ci)
        results[rule["code"]] = mine
        same = mine["population"] == rule["population"] and mine["defects"] == rule["defects"]
        mismatches += not same
        lines_out.append((rule, mine, "equal" if same else "DIFFERENT"))

    sn_score = card["score"]
    py_score = weighted_score(
        [(r["weight"], results[r["code"]]["score"]) for r in card["results"] if r["code"] in results]
    )
    score_ok = sn_score is not None and py_score is not None and abs(sn_score - py_score) <= 0.01 and not mismatches

    ground_truth = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))
    gt_rows = ground_truth_rows(results, ground_truth)
    gt_found = sum(r["found"] for r in gt_rows)
    gt_injected = sum(r["injected"] for r in gt_rows)

    md = [
        "# DQ scorecard: ServiceNow vs. independent recomputation",
        "",
        f"Generated {date.today().isoformat()} by `python3 loader/check_dq_scorecard.py` against the personal "
        f"developer instance. Scorecard «{card['scorecard']}», snapshot of {card['created_on']} UTC.",
        "",
        f"**Score in ServiceNow {sn_score}, recomputed from the raw records {py_score}: "
        f"{'equal' if score_ok else 'DIFFERENT'}** ({len(results)} rules, population and defects compared per rule).",
        "",
        "| Rule | Name | Weight | Population SN / Python | Defects SN / Python | Score | Result |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for rule, mine, verdict in lines_out:
        if mine is None:
            md.append(f"| {rule['code']} | {rule['rule']} | {rule['weight']} | | | | {verdict} |")
            continue
        md.append(
            f"| {rule['code']} | {rule['rule']} | {rule['weight']} | {rule['population']} / {mine['population']} | "
            f"{rule['defects']} / {mine['defects']} | {rule['score']} | {verdict} |"
        )
    md += [
        "",
        "## Ground truth",
        "",
        f"Seven generic rules correspond to an error type the test data generator injected on purpose. "
        f"They find **{gt_found} of {gt_injected}** injected issues of these types in the CMDB as it is now.",
        "",
        "| Rule | Injected error type | injected | found by the rule | not shown in the CMDB | additional records |",
        "|---|---|---:|---:|---|---|",
    ]
    for r in gt_rows:
        extra = ", ".join(r["additional"]) or (
            "duplicate partners: " + ", ".join(r["partners"]) if r["partners"] else "–"
        )
        md.append(
            f"| {r['code']} | {r['type']} | {r['injected']} | {r['found']} | {', '.join(r['not_shown']) or '–'} | "
            f"{extra} |"
        )
    md += [
        "",
        "«Not shown in the CMDB»: no longer visible on the CMDB, either corrected by the platform on load (C02, C04; "
        "see `docs/data_quality.md`, the import check reports them) or remediated afterwards (C07: devices returned "
        "or reported lost through the leaver cases of the ITAM Toolkit). «Additional records»: flagged by the generic "
        "rule although no error of this type was injected for them (the three scan-only CIs the IRE did not merge).",
    ]
    report.write_text("\n".join(md) + "\n", encoding="utf-8")

    print(f"Scorecard {card['scorecard']}, Snapshot {card['created_on']} UTC")
    for rule, mine, verdict in lines_out:
        detail = f"{rule['defects']}/{rule['population']} vs. {mine['defects']}/{mine['population']}" if mine else ""
        print(f"  {rule['code']} {rule['rule'][:52]:<52} {detail:<20} {verdict}")
    print(f"Score ServiceNow {sn_score}, Python {py_score}: {'gleich' if score_ok else 'VERSCHIEDEN'}")
    print(f"Ground Truth: {gt_found} von {gt_injected} eingebauten Fehlern dieser Typen gefunden")
    for r in gt_rows:
        if r["not_shown"] or r["additional"]:
            print(f"  {r['code']} nicht sichtbar: {r['not_shown']} zusätzlich: {r['additional']}")
    print(f"Bericht: {report.relative_to(ROOT)}")
    return 0 if score_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
