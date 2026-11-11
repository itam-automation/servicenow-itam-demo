#!/usr/bin/env python3
"""Entfernt die Testdaten, die der Loader in der PDI angelegt hat.

Sicherheitsregeln:
- Auswahl nur über die Herkunft, nie über Namen: Datensätze, die der
  Integrationsbenutzer angelegt hat (sys_created_by = SN_USER, seit es ihn gibt).
  Vorhandene Demo-Datensätze, die der Loader nur wiederverwendet hat
  (z. B. der Hersteller «Lenovo»), bleiben unberührt.
- Assets legt ServiceNow selbst aus den CIs an (Job «Create asset delayed sync»,
  läuft als admin). Sie werden über ihr CI ausgewählt: Asset, dessen CI der
  Loader angelegt hat.
- Ohne --execute wird nur gezählt und gesichert (IDs und Gesamtzahlen in
  loader/output/reset_backup_*.json). Mit --execute wird nur gelöscht, wenn jede
  Zahl der Erwartung entspricht; danach müssen die Gesamtzahlen von alm_hardware
  und cmdb_ci_hardware um genau die gesicherten Mengen gesunken sein.
- Assets und IRE-Quellenschlüssel darf der Loader nicht löschen (Rollen asset
  bzw. admin). Diese löscht admin vorher mit derselben Auswahl; das Skript
  prüft, dass die Assets weg sind.
- Nie gelöscht: Integrationsbenutzer, admin, Konfiguration (Datenquellen,
  Transform Maps, Abgleichsregeln, Reports).

Aufruf aus dem Projektordner:
    python3 loader/reset_testdata.py            # zählen und sichern
    python3 loader/reset_testdata.py --execute  # prüfen, löschen, nachzählen
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sn_client import SNClient, SNError  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "output"
PROTECTED_USERS = ("admin",)

# label, Tabelle, erwartete Anzahl, Auswahl, wer löscht
TARGETS = [
    ("Assets (über CI-Herkunft)", "alm_hardware", 197, "lineage", "admin"),
    ("IRE-Quellenschlüssel", "sys_object_source", 212, "creator", "admin"),
    ("CIs", "cmdb_ci_hardware", 203, "creator", "loader"),
    ("Benutzer", "sys_user", 130, "creator", "loader"),
    ("Modelle", "cmdb_hardware_product_model", 35, "creator", "loader"),
    ("Abteilungen", "cmn_department", 9, "creator", "loader"),
    ("Standorte", "cmn_location", 5, "creator", "loader"),
    ("Firma und neu angelegte Hersteller", "core_company", 9, "creator", "loader"),
]
TOTALS = {"alm_hardware": "Assets (über CI-Herkunft)", "cmdb_ci_hardware": "CIs"}


class Selection:
    def __init__(self, client: SNClient):
        me = client.get_records("sys_user", f"user_name={client.user}", "sys_created_on")
        if len(me) != 1:
            raise SystemExit(f"Integrationsbenutzer {client.user} nicht eindeutig gefunden")
        self.client = client
        self.since = me[0]["sys_created_on"]

    def query(self, table: str, kind: str) -> str:
        user = self.client.user
        if kind == "lineage":
            return f"ci.sys_created_by={user}^ci.sys_created_on>={self.since}"
        query = f"sys_created_by={user}^sys_created_on>={self.since}"
        if table == "sys_user":
            query += f"^user_nameNOT IN{','.join((user, *PROTECTED_USERS))}"
        return query

    def count(self, table: str, kind: str) -> int | None:
        try:
            return self.client.count(table, self.query(table, kind))
        except SNError:
            return None  # kein Leserecht (nur admin)


def latest_backup() -> Path:
    backups = sorted(OUT_DIR.glob("reset_backup_*.json"))
    if not backups:
        raise SystemExit("Keine Sicherung gefunden. Zuerst ohne --execute laufen lassen.")
    return backups[-1]


def count_and_backup(client: SNClient, sel: Selection) -> bool:
    ok = True
    counts = {}
    print(f"  {'Tabelle':<48} {'erwartet':>8} {'gefunden':>9}  löscht")
    for label, table, expected, kind, who in TARGETS:
        found = sel.count(table, kind)
        counts[label] = found
        if found is None:
            mark = "nur als admin zählbar"
        else:
            mark = "ok" if found == expected else "ABWEICHUNG"
            ok &= found == expected
        shown = found if found is not None else "-"
        print(f"  {label + ' (' + table + ')':<48} {expected:>8} {shown:>9}  {who:<6} {mark}")
    backup = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "filter_since": sel.since,
        "totals_before": {t: client.count(t) for t in TOTALS},
        "counts": counts,
        "cis": client.get_records("cmdb_ci_hardware", sel.query("cmdb_ci_hardware", "creator"),
                                  "sys_id,name,sys_class_name"),
        "assets": client.get_records("alm_hardware", sel.query("alm_hardware", "lineage"), "sys_id,asset_tag,ci"),
    }
    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / f"reset_backup_{datetime.now():%Y%m%d_%H%M%S}.json"
    path.write_text(json.dumps(backup, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  Gesamtzahlen vorher: {backup['totals_before']}")
    print(f"  Gesichert: {len(backup['cis'])} CI-IDs, {len(backup['assets'])} Asset-IDs -> {path.name}")
    names = sorted(c["name"] for c in client.get_records("core_company", sel.query("core_company", "creator"), "name"))
    print("  Firmen/Hersteller, die gelöscht würden: " + ", ".join(names))
    return ok


def execute(client: SNClient, sel: Selection) -> int:
    backup = json.loads(latest_backup().read_text(encoding="utf-8"))
    remaining_assets = sel.count("alm_hardware", "lineage")
    if remaining_assets:
        print(f"Abbruch: noch {remaining_assets} Assets vorhanden. Diese zuerst als admin löschen.")
        return 1
    backup_ci_ids = {c["sys_id"] for c in backup["cis"]}
    for label, table, expected, kind, who in TARGETS:
        if who != "loader":
            continue
        if table == "cmdb_ci_hardware":
            # Beim Löschen eines Assets löscht ServiceNow das zugehörige CI mit.
            # Übrig sein dürfen nur CIs aus der Sicherung (hier die Firewalls ohne Asset).
            remaining = client.get_records(table, sel.query(table, kind), "sys_id,name,sys_class_name")
            foreign = [r for r in remaining if r["sys_id"] not in backup_ci_ids]
            if foreign:
                print(f"Abbruch: {len(foreign)} CIs nicht in der Sicherung, z. B. {foreign[0]['name']}")
                return 1
            classes = sorted({r["sys_class_name"] for r in remaining})
            print(f"  CIs: noch {len(remaining)} von {expected} (Rest nach Asset-Löschung, Klassen: {classes})")
            continue
        found = sel.count(table, kind)
        if found != expected:
            print(f"Abbruch vor dem Löschen: {label} {found} statt {expected}. Erst klären.")
            return 1
    for label, table, _, kind, who in TARGETS:
        if who != "loader":
            continue
        records = client.get_records(table, sel.query(table, kind), "sys_id")
        for i, rec in enumerate(records, start=1):
            client.delete(table, rec["sys_id"])
            print(f"  {label}: {i}/{len(records)} gelöscht", end="\r", flush=True)
        print()

    print("Nachzählung:")
    ok = True
    for label, table, _, kind, _who in TARGETS:
        found = sel.count(table, kind)
        ok &= found in (0, None)
        print(f"  {label + ' (' + table + ')':<48} {found if found is not None else 'nur als admin zählbar':>9}")
    for table, label in TOTALS.items():
        before, now = backup["totals_before"][table], client.count(table)
        expected_drop = backup["counts"][label]
        good = before - now == expected_drop
        ok &= good
        print(f"  Gesamt {table}: {before} -> {now} (gesunken um {before - now}, erwartet {expected_drop})"
              f"  {'ok' if good else 'ABWEICHUNG'}")
    left = [c["sys_id"] for c in backup["cis"]]
    still = sum(client.count("cmdb_ci_hardware", "sys_idIN" + ",".join(left[i:i + 100]))
                for i in range(0, len(left), 100))
    ok &= still == 0
    print(f"  Gesicherte CI-IDs noch vorhanden: {still}")
    return 0 if ok else 1


def apply_expectations(pairs: list[str]) -> None:
    """--expect tabelle=anzahl: andere Erwartung als ein Volllauf (nicht genannte Tabellen: 0)."""
    override = {}
    for pair in pairs:
        table, _, number = pair.partition("=")
        if table not in {t[1] for t in TARGETS} or not number.isdigit():
            raise SystemExit(f"Ungültige Erwartung: {pair}")
        override[table] = int(number)
    TARGETS[:] = [(label, table, override.get(table, 0), kind, who) for label, table, _, kind, who in TARGETS]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Entfernt die vom Loader angelegten Testdaten.")
    parser.add_argument("--execute", action="store_true", help="wirklich löschen (sonst nur zählen und sichern)")
    parser.add_argument("--expect", nargs="+", metavar="TABELLE=ANZAHL",
                        help="erwartete Anzahl je Tabelle statt des Volllaufs, z. B. cmn_location=5")
    args = parser.parse_args(argv)
    if args.expect:
        apply_expectations(args.expect)
    client = SNClient.from_env()
    sel = Selection(client)
    print(f"Instanz {client.base_url}, Auswahl: angelegt von {client.user} seit {sel.since} (UTC)")
    if args.execute:
        return execute(client, sel)
    ok = count_and_backup(client, sel)
    print("Gezählt und gesichert. Zum Löschen: --execute" if ok else "Abweichung: nichts löschen, erst klären.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
