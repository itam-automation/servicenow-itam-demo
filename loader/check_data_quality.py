#!/usr/bin/env python3
"""Datenqualitäts-Check der CMDB gegen die bekannte Wahrheit (ground_truth.json).

Liest die CIs der Muster AG und die Ergebnisse der IRE aus der Staging-Tabelle
über REST (nur lesend). Für jeden Fehler, den der Generator eingebaut hat, wird
festgestellt, wodurch er erkannt wurde:

- IRE: Dublette aus dem Netzwerk-Scan auf das vorhandene CI zusammengeführt
- Report: eine der Prüfregeln (gleiche Regeln wie die Reports «ITAM DQ» in ServiceNow)
- Plattform: beim Laden von ServiceNow selbst bereinigt (z. B. Standort vom Benutzer übernommen)
- nicht erkannt

Ergebnis als Markdown in docs/data_quality.md, Kennzahl «X von Y erkannt».

Aufruf aus dem Projektordner:
    python3 loader/check_data_quality.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "testdata"))

from generate_testdata import MODELS  # noqa: E402
from sn_client import SNClient  # noqa: E402
from staging import BY_KEY  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "testdata" / "output"
REPORT = ROOT / "docs" / "data_quality.md"

IN_USE = ("1", "3")  # Installed, In Maintenance
RETIRED = "7"
ENDPOINT_CLASSES = ("cmdb_ci_computer", "cmdb_ci_hardware")  # Laptops/Desktops, Smartphones (exakte Klasse)
CANONICAL_MANUFACTURERS = {m.manufacturer for m in MODELS}
DUPLICATE_TYPES = ("duplicate_same_serial", "duplicate_serial_variant", "duplicate_same_name_no_serial")

ISSUE_LABELS = {
    "missing_serial_number": "Missing serial number",
    "missing_location": "Missing location",
    "manufacturer_name_variant": "Manufacturer name variant (e.g. «DELL»)",
    "installed_without_user": "Endpoint in use without assigned user",
    "retired_with_user": "Retired endpoint still assigned",
    "assigned_to_inactive_user": "In use by an inactive user (leaver)",
    "duplicate_same_serial": "Duplicate from scan: same serial, FQDN name",
    "duplicate_serial_variant": "Duplicate from scan: serial in other spelling, other MAC",
    "duplicate_same_name_no_serial": "Duplicate from scan: same name, no serial",
}
DETECTED_BY = ("IRE", "Report", "Platform", "not detected")


def normalize_serial(serial: str) -> str:
    return "".join(serial.split()).upper()


def fetch(client: SNClient) -> tuple[list[dict], dict[str, str], dict[str, str]]:
    fields = ",".join([
        "name", "serial_number", "asset_tag", "sys_class_name", "install_status", "discovery_source",
        "warranty_expiration", "manufacturer.name", "location.name", "assigned_to.user_name", "assigned_to.active",
        "assigned_to.location.name",
    ])
    cis = client.get_records("cmdb_ci_hardware", "company.name=Muster AG", fields)
    computers = client.get_records("cmdb_ci_computer", "company.name=Muster AG", "name,os")
    os_by_name = {c["name"]: c["os"] for c in computers}
    # Neueste Staging-Zeile je Quell-ID: welches CI hat die IRE dafür geschrieben oder gefunden?
    staged = client.get_records(BY_KEY["devices"].table, "ORDERBYsys_created_on", "u_source_id,u_ire_ci")
    ire_ci = {row["u_source_id"]: row["u_ire_ci"] for row in staged}
    return cis, os_by_name, ire_ci


def apply_rules(cis: list[dict]) -> dict[str, set[str]]:
    """Prüfregeln (wie die Reports «ITAM DQ 1-7»). Gibt je Regel die Namen der betroffenen CIs zurück."""
    found: dict[str, set[str]] = {key: set() for key in ISSUE_LABELS if key not in DUPLICATE_TYPES}
    found["duplicates"] = set()
    by_serial: dict[str, list[str]] = {}
    for ci in cis:
        name, status = ci["name"], ci["install_status"]
        endpoint = ci["sys_class_name"] in ENDPOINT_CLASSES
        if not ci["serial_number"].strip():
            found["missing_serial_number"].add(name)
        else:
            by_serial.setdefault(normalize_serial(ci["serial_number"]), []).append(name)
        if not ci["location.name"]:
            found["missing_location"].add(name)
        if ci["manufacturer.name"] and ci["manufacturer.name"] not in CANONICAL_MANUFACTURERS:
            found["manufacturer_name_variant"].add(name)
        if endpoint and status in IN_USE and not ci["assigned_to.user_name"]:
            found["installed_without_user"].add(name)
        if endpoint and status == RETIRED and ci["assigned_to.user_name"]:
            found["retired_with_user"].add(name)
        if status in IN_USE and ci["assigned_to.user_name"] and ci["assigned_to.active"] == "false":
            found["assigned_to_inactive_user"].add(name)
    for names in by_serial.values():
        if len(names) > 1:
            found["duplicates"].update(names)
    return found


def platform_reason(issue: dict, ci: dict | None) -> str:
    """Bekanntes Plattformverhalten, das einen eingebauten Fehler beim Laden aufgehoben hat."""
    if ci is None:
        return ""
    if (issue["type"] == "missing_location" and ci["assigned_to.user_name"]
            and ci["location.name"] == ci["assigned_to.location.name"]):
        return "location taken over from the assigned user"
    if issue["type"] == "manufacturer_name_variant" and " statt " in issue["detail"]:
        variant, canonical = issue["detail"].split(" statt ", 1)
        if variant.lower() == canonical.lower():
            return f"«{variant}» differs only in case, matched to existing «{canonical}» on load"
    return ""


def classify(ground_truth: dict, cis: list[dict], found: dict[str, set[str]],
             ire_ci: dict[str, str]) -> list[dict]:
    """Ordnet jedem eingebauten Fehler zu, wodurch er erkannt wurde."""
    ci_by_name = {c["name"]: c for c in cis}
    rows = []
    for issue in ground_truth["issues"]:
        kind, name = issue["type"], issue["name"]
        how, note = "not detected", ""
        if kind in DUPLICATE_TYPES:
            dup, orig = ire_ci.get(issue["source_id"]), ire_ci.get(issue["duplicate_of"])
            if dup and dup == orig:
                how = "IRE"
            elif name in found["duplicates"]:
                how, note = "Report", "separate CI, found by duplicate check"
        elif name in found[kind]:
            how = "Report"
        else:
            note = platform_reason(issue, ci_by_name.get(name))
            if note:
                how = "Platform"
        rows.append({**issue, "detected_by": how, "note": note})
    return rows


def main() -> int:
    ground_truth = json.loads((DATA_DIR / "ground_truth.json").read_text(encoding="utf-8"))
    client = SNClient.from_env()
    cis, os_by_name, ire_ci = fetch(client)
    found = apply_rules(cis)
    rows = classify(ground_truth, cis, found, ire_ci)

    total = len(rows)
    counts = Counter(r["detected_by"] for r in rows)
    detected = counts["IRE"] + counts["Report"]
    expected_names = {r["name"] for r in rows}
    unexpected = {key: names - expected_names for key, names in found.items() if key != "duplicates"}
    unexpected = {k: v for k, v in unexpected.items() if v}

    in_use = [c for c in cis if c["install_status"] in IN_USE]
    today = ground_truth["parameters"]["reference_date"]
    kpis = [
        ("Warranty ends in 2027 (in use)", ground_truth["kpis"]["warranty_ends_2027_in_use"],
         sum(c["warranty_expiration"].startswith("2027") for c in in_use)),
        ("Warranty expired (in use)", ground_truth["kpis"]["warranty_expired_in_use"],
         sum(bool(c["warranty_expiration"]) and c["warranty_expiration"] < today for c in in_use)),
        ("Windows 10 (in use)", ground_truth["kpis"]["windows10_in_use"],
         sum(os_by_name.get(c["name"], "").startswith("Windows 10") for c in in_use)),
    ]

    headline = (f"**{detected} of {total} injected data quality issues detected** "
                f"({counts['IRE']} merged by the IRE, {counts['Report']} found by the reports); "
                f"{counts['Platform']} were already resolved by the platform on load, "
                f"{counts['not detected']} not detected.")
    lines = [
        "# Data quality: measured against the ground truth",
        "",
        f"Generated {date.today().isoformat()} by `python3 loader/check_data_quality.py` against the personal "
        f"developer instance: {len(cis)} CIs of Muster AG. The test data generator injected {total} issues on "
        "purpose (`testdata/output/ground_truth.json`); this check classifies how each one was caught.",
        "",
        headline,
        "",
        "| Issue type | injected | IRE | Report | Platform | not detected |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    by_type: dict[str, Counter] = {}
    for r in rows:
        by_type.setdefault(r["type"], Counter())[r["detected_by"]] += 1
    for kind, label in ISSUE_LABELS.items():
        c = by_type.get(kind, Counter())
        lines.append(f"| {label} | {sum(c.values())} | " + " | ".join(str(c[d]) for d in DETECTED_BY) + " |")
    notes = [r for r in rows if r["detected_by"] in ("Platform", "not detected") or r["note"]]
    if notes:
        lines += ["", "Details:", ""]
        lines += [f"- {r['name']} ({ISSUE_LABELS[r['type']]}): {r['detected_by']}"
                  + (f", {r['note']}" if r["note"] else "") for r in notes]
    if unexpected:
        lines += ["", "Additional findings not injected by the generator:", ""]
        lines += [f"- {ISSUE_LABELS[k]}: {', '.join(sorted(v))}" for k, v in unexpected.items()]
    lines += ["", "| KPI | expected | in ServiceNow |", "|---|---:|---:|"]
    lines += [f"| {title} | {exp} | {got} |" for title, exp, got in kpis]

    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"{len(cis)} CIs der Muster AG")
    print(f"  {detected} von {total} eingebauten Fehlern erkannt (IRE {counts['IRE']}, Reports {counts['Report']}), "
          f"{counts['Platform']} beim Laden von der Plattform bereinigt, {counts['not detected']} nicht erkannt")
    for kind, label in ISSUE_LABELS.items():
        c = by_type.get(kind, Counter())
        print(f"    {label:<58} " + ", ".join(f"{d} {c[d]}" for d in DETECTED_BY if c[d]))
    for r in notes:
        print(f"    Hinweis: {r['name']}: {r['detected_by']} {r['note']}")
    for k, v in unexpected.items():
        print(f"    Zusätzlich gefunden ({k}): {', '.join(sorted(v))}")
    for title, exp, got in kpis:
        print(f"  {title:<40} erwartet {exp:3d}  gefunden {got:3d}")
    print(f"Bericht: {REPORT.relative_to(ROOT)}")
    return 0 if counts["not detected"] == 0 and all(exp == got for _, exp, got in kpis) else 1


if __name__ == "__main__":
    raise SystemExit(main())
