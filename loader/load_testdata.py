#!/usr/bin/env python3
"""Lädt die Testdaten der Muster AG über REST in die PDI.

1. Stammdaten über die Table API: Firma, Hersteller, Standorte, Abteilungen,
   Benutzer, Hardware-Modelle. Fehlendes wird angelegt, eigene Datensätze
   (company = Muster AG) werden aktualisiert, fremde (Demo-Daten) nie verändert.
2. Geräte über die Identification and Reconciliation API (IRE): zuerst der
   Inventar-Export, dann der Netzwerk-Scan. Die IRE entscheidet anhand der
   Hardware Rule, ob ein Gerät neu ist oder schon existiert.

Das Ergebnis jedes Laufs steht in loader/output/last_run.json und wird gegen
testdata/output/ground_truth.json abgeglichen.

Aufruf aus dem Projektordner:
    python3 loader/load_testdata.py --dry-run          # nichts schreiben, nur IRE-Probe
    python3 loader/load_testdata.py --step masterdata  # nur Stammdaten
    python3 loader/load_testdata.py --limit 5          # Stammdaten + 5 Geräte je Quelle
    python3 loader/load_testdata.py                    # alles
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mapping import (  # noqa: E402
    DATA_SOURCES,
    SOURCE_ORDER,
    References,
    build_ire_item,
    model_category,
    parse_ire_response,
)
from sn_client import SNClient, SNError  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "testdata" / "output"
OUT_FILE = Path(__file__).resolve().parent / "output" / "last_run.json"
COMPANY = "Muster AG"


def read_csv(name: str, data_dir: Path) -> list[dict]:
    with (data_dir / f"{name}.csv").open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def q(value: str) -> str:
    """Wert für eine Encoded Query: ^ würde die Abfrage trennen."""
    if "^" in value:
        raise ValueError(f"Wert mit ^ kann nicht abgefragt werden: {value!r}")
    return value


class MasterData:
    """Legt Stammdaten an oder findet sie. create=False nur nachschlagen (Probelauf)."""

    def __init__(self, client: SNClient, create: bool):
        self.client = client
        self.create = create
        self.stats: dict[str, Counter] = defaultdict(Counter)
        self.notes: list[str] = []

    def upsert(self, table: str, query: str, values: dict, company_id: str | None = None) -> str | None:
        fields = ",".join(["sys_id", "company", *values])
        found = self.client.get_records(table, query, fields)
        if found:
            rec = found[0]
            if company_id and rec.get("company") != company_id:
                self.stats[table]["fremd, nicht verändert"] += 1
                self.notes.append(f"{table}: {query} gehört nicht zur {COMPANY}, nicht verändert")
                return None
            diff = {k: v for k, v in values.items() if str(rec.get(k, "")) != str(v)}
            if diff and self.create and company_id:
                self.client.update(table, rec["sys_id"], diff)
                self.stats[table]["aktualisiert"] += 1
            else:
                self.stats[table]["vorhanden"] += 1
            return rec["sys_id"]
        if not self.create:
            self.stats[table]["fehlt"] += 1
            return None
        rec = self.client.create(table, values)
        self.stats[table]["angelegt"] += 1
        return rec["sys_id"]

    def load(self, data: dict[str, list[dict]]) -> References:
        refs = References()

        company_id = self.upsert("core_company", f"name={q(COMPANY)}", {"name": COMPANY})
        if company_id:
            refs.company[COMPANY] = company_id

        # Hersteller: vorhandene wiederverwenden (auch Demo-Daten), fehlende anlegen.
        # Varianten wie «DELL» werden bewusst so angelegt, wie die Quelle sie liefert.
        names = sorted({m["manufacturer"] for m in data["models"]} | {d["manufacturer"] for d in data["devices"]})
        for name in names:
            found = self.client.get_records("core_company", f"name={q(name)}", "sys_id,name")
            if found:
                refs.manufacturer[name] = found[0]["sys_id"]
                self.stats["core_company (Hersteller)"]["vorhanden"] += 1
                if found[0]["name"] != name:
                    self.notes.append(f"Hersteller «{name}» aufgelöst auf vorhandenen Eintrag «{found[0]['name']}»")
            elif self.create:
                rec = self.client.create("core_company", {"name": name, "manufacturer": "true"})
                refs.manufacturer[name] = rec["sys_id"]
                self.stats["core_company (Hersteller)"]["angelegt"] += 1
            else:
                self.stats["core_company (Hersteller)"]["fehlt"] += 1

        for loc in data["locations"]:
            values = {k: loc[k] for k in ("name", "street", "zip", "city", "country")}
            if company_id:
                values["company"] = company_id
            sys_id = self.upsert("cmn_location", f"name={q(loc['name'])}", values, company_id)
            if sys_id:
                refs.location[loc["name"]] = sys_id

        for dep in data["departments"]:
            # Die Kostenstelle landet im Feld «ID», eine eigene Kostenstellen-Tabelle braucht die Demo nicht.
            values = {"name": dep["name"], "id": dep["cost_center"]}
            if company_id:
                values["company"] = company_id
            query = f"name={q(dep['name'])}^company={company_id}" if company_id else f"name={q(dep['name'])}"
            sys_id = self.upsert("cmn_department", query, values, company_id)
            if sys_id:
                refs.department[dep["name"]] = sys_id

        for user in data["users"]:
            values = {k: user[k] for k in ("user_name", "first_name", "last_name", "email", "active")}
            for column, mapping in (("department", refs.department), ("location", refs.location)):
                if mapping.get(user[column]):
                    values[column] = mapping[user[column]]
            if company_id:
                values["company"] = company_id
            sys_id = self.upsert("sys_user", f"user_name={q(user['user_name'])}", values, company_id)
            if sys_id:
                refs.user[user["user_name"]] = sys_id

        categories = {
            c["name"]: c["sys_id"]
            for c in self.client.get_records("cmdb_model_category", "", "sys_id,name")
        }
        device_category = {d["model_id"]: d["category"] for d in data["devices"]}
        for model in data["models"]:
            manufacturer_id = refs.manufacturer.get(model["manufacturer"])
            if not manufacturer_id:
                continue
            values = {"name": model["name"], "manufacturer": manufacturer_id}
            category = categories.get(model_category(model["category"], model["manufacturer"]))
            if category:
                values["cmdb_model_category"] = category
            query = f"name={q(model['name'])}^manufacturer={manufacturer_id}"
            found = self.client.get_records("cmdb_hardware_product_model", query, "sys_id")
            if found:
                refs.model[model["name"]] = found[0]["sys_id"]
                self.stats["cmdb_hardware_product_model"]["vorhanden"] += 1
            elif self.create and model["name"] in device_category:
                rec = self.client.create("cmdb_hardware_product_model", values)
                refs.model[model["name"]] = rec["sys_id"]
                self.stats["cmdb_hardware_product_model"]["angelegt"] += 1
            elif not self.create:
                self.stats["cmdb_hardware_product_model"]["fehlt"] += 1
        return refs


def load_cis(client: SNClient, devices: list[dict], refs: References, dry_run: bool,
             batch_size: int, limit: int | None, sources: tuple[str, ...] = SOURCE_ORDER) -> list[dict]:
    results = []
    for source in sources:
        rows = [d for d in devices if d["source"] == source][:limit]
        data_source = DATA_SOURCES[source]
        for start in range(0, len(rows), batch_size):
            batch = rows[start:start + batch_size]
            built = [build_ire_item(row, refs) for row in batch]
            try:
                parsed = parse_ire_response(client.identify_reconcile([b[0] for b in built], data_source, dry_run))
            except SNError as err:
                # Ganze Ladung abgelehnt: einzeln wiederholen, um das fehlerhafte Gerät zu finden
                parsed = []
                for item, _ in built:
                    try:
                        parsed.extend(parse_ire_response(client.identify_reconcile([item], data_source, dry_run)))
                    except SNError as single:
                        parsed.append({"class": item["className"], "operation": "FEHLER", "sys_id": "",
                                       "errors": [single.message or str(single)], "identification": []})
                if not parsed:
                    raise err
            if len(parsed) != len(batch):
                raise RuntimeError(f"IRE lieferte {len(parsed)} Ergebnisse für {len(batch)} Geräte")
            for row, (_, missing), res in zip(batch, built, parsed):
                results.append({"source_id": row["source_id"], "source": source, "name": row["name"],
                                "missing_references": missing, **res})
            done = start + len(batch)
            print(f"  {data_source}: {done}/{len(rows)}", end="\r", flush=True)
        if rows:
            print()
    return results


def compare_with_ground_truth(results: list[dict], ground_truth: dict) -> list[str]:
    sys_id_of = {r["source_id"]: r["sys_id"] for r in results}
    lines = []
    by_type: dict[str, Counter] = defaultdict(Counter)
    for issue in ground_truth["issues"]:
        if "duplicate_of" not in issue or issue["source_id"] not in sys_id_of:
            continue
        dup, orig = sys_id_of[issue["source_id"]], sys_id_of.get(issue["duplicate_of"])
        verdict = "erkannt (gleiche CI)" if dup and dup == orig else "nicht erkannt (eigene CI)"
        by_type[issue["type"]][verdict] += 1
    for kind, counter in by_type.items():
        lines.append(f"    {kind}: " + ", ".join(f"{n} {v}" for v, n in counter.items()))
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lädt die Testdaten der Muster AG in die PDI.")
    parser.add_argument("--step", choices=("all", "masterdata", "cis"), default="all")
    parser.add_argument("--dry-run", action="store_true", help="nichts schreiben; IRE nur identifizieren lassen")
    parser.add_argument("--limit", type=int, default=None, help="höchstens so viele Geräte je Quelle")
    parser.add_argument("--source", choices=("all", "inventory", "scan"), default="all",
                        help="nur eine Quelle laden (Scan erst nach dem Inventar, sonst entstehen Dubletten)")
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    args = parser.parse_args(argv)

    data = {name: read_csv(name, args.data_dir)
            for name in ("locations", "departments", "users", "models", "devices")}
    client = SNClient.from_env()
    print(f"Instanz {client.base_url}, Benutzer {client.user}{', PROBELAUF' if args.dry_run else ''}")

    create_masterdata = not args.dry_run and args.step in ("all", "masterdata")
    print("Stammdaten " + ("anlegen/abgleichen" if create_masterdata else "nachschlagen") + " ...")
    master = MasterData(client, create=create_masterdata)
    refs = master.load(data)
    for table, counter in master.stats.items():
        print(f"  {table}: " + ", ".join(f"{n} {k}" for k, n in counter.items()))

    results: list[dict] = []
    if args.step in ("all", "cis"):
        print("Geräte über die IRE " + ("prüfen" if args.dry_run else "laden") + " ...")
        sources = {"all": SOURCE_ORDER, "inventory": SOURCE_ORDER[:1], "scan": SOURCE_ORDER[1:]}[args.source]
        results = load_cis(client, data["devices"], refs, args.dry_run, args.batch_size, args.limit, sources)
        for source in SOURCE_ORDER:
            ops = Counter(r["operation"] for r in results if r["source"] == source)
            if ops:
                print(f"  {DATA_SOURCES[source]}: " + ", ".join(f"{n} {op}" for op, n in sorted(ops.items())))
        errors = [r for r in results if r["errors"]]
        missing = Counter(m.split("=")[0] for r in results for m in r["missing_references"])
        if errors:
            print(f"  Geräte mit Fehlern: {len(errors)}, zum Beispiel {errors[0]['source_id']}: {errors[0]['errors'][:2]}")
        if missing:
            print("  Nicht auflösbare Referenzen: " + ", ".join(f"{n}× {k}" for k, n in missing.items()))
        ground_truth = json.loads((args.data_dir / "ground_truth.json").read_text(encoding="utf-8"))
        comparison = compare_with_ground_truth(results, ground_truth)
        if comparison:
            print("  Dubletten aus dem Netzwerk-Scan:")
            print("\n".join(comparison))

    OUT_FILE.parent.mkdir(exist_ok=True)
    OUT_FILE.write_text(json.dumps({
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "instance": client.base_url,
        "args": {k: str(v) for k, v in vars(args).items()},
        "masterdata": {t: dict(c) for t, c in master.stats.items()},
        "notes": master.notes,
        "devices": results,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Ergebnis: {OUT_FILE.relative_to(ROOT)}")
    return 1 if any(r["operation"] == "FEHLER" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
