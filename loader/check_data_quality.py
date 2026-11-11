#!/usr/bin/env python3
"""Datenqualitäts-Check der CMDB gegen die bekannte Wahrheit (ground_truth.json).

Liest die CIs der Muster AG über REST (nur lesend), wendet die Prüfregeln an
und vergleicht das Ergebnis mit den Fehlern, die der Generator eingebaut hat.
Abweichungen werden erklärt, nicht versteckt. Ergebnis als Markdown in
docs/datenqualitaet.md.

Aufruf aus dem Projektordner:
    python3 loader/check_data_quality.py
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "testdata"))

from generate_testdata import MODELS  # noqa: E402
from sn_client import SNClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "testdata" / "output"
REPORT = ROOT / "docs" / "datenqualitaet.md"

IN_USE = ("1", "3")  # Installed, In Maintenance
RETIRED = "7"
ENDPOINT_CLASSES = ("cmdb_ci_computer", "cmdb_ci_hardware")  # Laptops/Desktops, Smartphones (exakte Klasse)
CANONICAL_MANUFACTURERS = {m.manufacturer for m in MODELS}

RULES = [
    # Schlüssel in ground_truth, Titel
    ("missing_serial_number", "Seriennummer fehlt"),
    ("missing_location", "Standort fehlt"),
    ("manufacturer_name_variant", "Herstellername nicht in Normschreibweise"),
    ("installed_without_user", "Endgerät in Betrieb ohne Benutzer"),
    ("retired_with_user", "Ausgemustert, aber noch zugewiesen"),
    ("assigned_to_inactive_user", "In Betrieb bei inaktivem Benutzer"),
    ("duplicates", "Dubletten (gleiche Seriennummer nach Normalisierung)"),
]


def normalize_serial(serial: str) -> str:
    return serial.strip().upper()


def fetch(client: SNClient) -> tuple[list[dict], dict[str, str]]:
    fields = ",".join([
        "name", "serial_number", "asset_tag", "sys_class_name", "install_status", "discovery_source",
        "warranty_expiration", "manufacturer.name", "location.name", "assigned_to.user_name", "assigned_to.active",
        "assigned_to.location.name",
    ])
    cis = client.get_records("cmdb_ci_hardware", "company.name=Muster AG", fields)
    os_by_name = {c["name"]: c["os"] for c in client.get_records("cmdb_ci_computer", "company.name=Muster AG", "name,os")}
    return cis, os_by_name


def apply_rules(cis: list[dict]) -> dict[str, set[str]]:
    """Gibt je Regel die Namen der betroffenen CIs zurück."""
    found: dict[str, set[str]] = {key: set() for key, _ in RULES}
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


def expected_sets(ground_truth: dict, devices: list[dict]) -> tuple[dict[str, set[str]], dict[str, str]]:
    """Erwartete CI-Namen je Regel. Dubletten: das Original und die nicht zusammengeführte Scan-Kopie."""
    name_of = {d["source_id"]: d["name"] for d in devices}
    expected: dict[str, set[str]] = {key: set() for key, _ in RULES}
    details: dict[str, str] = {}
    for issue in ground_truth["issues"]:
        details[issue["name"]] = issue["detail"]
        if issue["type"] in expected:
            expected[issue["type"]].add(issue["name"])
        elif issue["type"] == "duplicate_serial_variant":
            # Nur diese Dublettenart landet als eigene CI; die anderen führt die IRE zusammen.
            expected["duplicates"].update({issue["name"], name_of[issue["duplicate_of"]]})
    return expected, details


def platform_reason(key: str, ci: dict | None, detail: str) -> str:
    """Bekanntes Plattformverhalten, das einen eingebauten Fehler beim Laden aufgehoben hat."""
    if ci is None:
        return ""
    if (key == "missing_location" and ci["assigned_to.user_name"]
            and ci["location.name"] == ci["assigned_to.location.name"]):
        return "Standort vom zugewiesenen Benutzer übernommen"
    if key == "manufacturer_name_variant" and " statt " in detail:
        variant, canonical = detail.split(" statt ", 1)
        if variant.lower() == canonical.lower():
            return "Variante unterscheidet sich nur in Gross-/Kleinschreibung, beim Laden dem vorhandenen Hersteller zugeordnet"
    return ""


def explain(key: str, extra: set[str], missing: set[str], scan_inserts: set[str], details: dict[str, str],
            ci_by_name: dict[str, dict]) -> str:
    parts = []
    from_dupes = extra & scan_inserts
    if from_dupes:
        parts.append(f"{len(from_dupes)} zusätzlich aus nicht erkannten Scan-Dubletten (dort fehlen diese Angaben)")
    other_extra = extra - scan_inserts
    if other_extra:
        parts.append("unerwartet: " + ", ".join(sorted(other_extra)))
    for name in sorted(missing):
        detail = details.get(name, "")
        reason = platform_reason(key, ci_by_name.get(name), detail)
        parts.append(f"nicht gefunden: {name} ({detail})" + (f", {reason}" if reason else ", Ursache unklar"))
    return " · ".join(parts) or "deckungsgleich"


def main() -> int:
    ground_truth = json.loads((DATA_DIR / "ground_truth.json").read_text(encoding="utf-8"))
    with (DATA_DIR / "devices.csv").open(encoding="utf-8", newline="") as f:
        devices = list(csv.DictReader(f))
    client = SNClient.from_env()
    cis, os_by_name = fetch(client)

    found = apply_rules(cis)
    expected, details = expected_sets(ground_truth, devices)
    scan_inserts = {c["name"] for c in cis if c["discovery_source"] == "MusterNetzScan" and not c["asset_tag"]}
    ci_by_name = {c["name"]: c for c in cis}

    in_use = [c for c in cis if c["install_status"] in IN_USE]
    today = ground_truth["parameters"]["reference_date"]
    kpis = [
        ("Garantieende 2027, in Betrieb", ground_truth["kpis"]["warranty_ends_2027_in_use"],
         sum(c["warranty_expiration"].startswith("2027") for c in in_use)),
        ("Garantie abgelaufen, in Betrieb", ground_truth["kpis"]["warranty_expired_in_use"],
         sum(bool(c["warranty_expiration"]) and c["warranty_expiration"] < today for c in in_use)),
        ("Windows 10, in Betrieb", ground_truth["kpis"]["windows10_in_use"],
         sum(os_by_name.get(c["name"], "").startswith("Windows 10") for c in in_use)),
    ]

    lines = [
        "# Datenqualität der CMDB",
        "",
        f"Stand {date.today().isoformat()}, persönliche Entwicklerinstanz (PDI), {len(cis)} CIs der Muster AG "
        f"(davon {len(scan_inserts)} nur aus dem Netzwerk-Scan, ohne Inventardatensatz).",
        "",
        "Vergleich der Prüfregeln mit den Fehlern, die der Testdaten-Generator bewusst eingebaut hat "
        "(`testdata/output/ground_truth.json`). Erzeugt mit `python3 loader/check_data_quality.py`.",
        "",
        "| Prüfregel | erwartet | gefunden | Erklärung |",
        "|---|---:|---:|---|",
    ]
    print(f"{len(cis)} CIs der Muster AG, davon {len(scan_inserts)} nur aus dem Scan")
    all_ok = True
    for key, title in RULES:
        extra = found[key] - expected[key]
        missing = expected[key] - found[key]
        note = explain(key, extra, missing, scan_inserts, details, ci_by_name)
        all_ok &= not (extra - scan_inserts) and "Ursache unklar" not in note
        lines.append(f"| {title} | {len(expected[key])} | {len(found[key])} | {note} |")
        print(f"  {title:<52} erwartet {len(expected[key]):3d}  gefunden {len(found[key]):3d}  {note}")
    lines += ["", "| Kennzahl | erwartet | in ServiceNow |", "|---|---:|---:|"]
    for title, exp, got in kpis:
        lines.append(f"| {title} | {exp} | {got} |")
        print(f"  {title:<52} erwartet {exp:3d}  gefunden {got:3d}")
    if found["duplicates"]:
        lines += ["", "Dubletten-Gruppen (gleiche Seriennummer nach Grossschreibung und Entfernen von Leerzeichen):", ""]
        groups: dict[str, list[str]] = {}
        for c in cis:
            if c["name"] in found["duplicates"]:
                groups.setdefault(normalize_serial(c["serial_number"]), []).append(c["name"])
        lines += [f"- {' / '.join(sorted(names))}" for names in groups.values()]

    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Bericht: {REPORT.relative_to(ROOT)}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
