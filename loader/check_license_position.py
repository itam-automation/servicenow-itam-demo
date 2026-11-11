#!/usr/bin/env python3
"""Prüft die Lizenzposition der Muster AG gegen die bekannte Wahrheit (nur lesend).

Zwei unabhängige Wege zur selben Zahl:
1. ServiceNow: Script Include «ItamLicensePosition» schreibt die Position in
   u_itam_license_position (nach jedem Lizenzimport und täglich). Gelesen über
   die Scripted REST API «ITAM Demo» (GET /license_position, Pfad in SN_ITAM_API).
2. Dieses Skript rechnet aus den Rohdaten der Instanz nach: Installationen
   (cmdb_software_instance), Softwarepakete und -modelle, Lizenzen (alm_license).
   Die Lizenzmetrik je Produkt kommt aus dem Softwarekatalog der Testdaten
   (software.csv), weil der Integrationsbenutzer das Feld «License type» nicht
   lesen darf.
Beide werden mit testdata/output/ground_truth.json («sam») verglichen; das
Ergebnis steht in docs/license_position.md.

Aufruf aus dem Projektordner:
    python3 loader/check_license_position.py
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sn_client import SNClient, SNError, load_env  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
GROUND_TRUTH = ROOT / "testdata" / "output" / "ground_truth.json"
CATALOG = ROOT / "testdata" / "output" / "software.csv"
REPORT = ROOT / "docs" / "license_position.md"
COMPANY = "Muster AG"
DEFAULT_API = "/api/<namespace>/itam_demo"

PER_USER = "Per named user"
PER_DEVICE = "Per workstation"
# Metrik der Testdaten -> Lizenztyp der Plattform (cmdb_sw_license_calculation)
METRIC = {"Per User": PER_USER, "Per Device": PER_DEVICE}
STATUS_EN = {
    "unterlizenziert": "under-licensed",
    "überlizenziert": "over-licensed",
    "ausgeglichen": "balanced",
    "ohne Lizenz": "no license",
    "ungenutzt": "unused (shelfware)",
}


def license_status(licensed: bool, rights: int, usage: int) -> str:
    """Gleiche Reihenfolge wie im Generator und im Script Include."""
    if not licensed:
        return "ohne Lizenz"
    if usage == 0:
        return "ungenutzt"
    if rights < usage:
        return "unterlizenziert"
    if rights > usage:
        return "überlizenziert"
    return "ausgeglichen"


def compute_position(installations: list[dict], licenses: list[dict], models: dict[str, dict]) -> list[dict]:
    """Lizenzposition je Softwaremodell.

    installations: {"model", "device", "user"} je Installation
    licenses:      {"model", "rights"} je Lizenz
    models:        Modell-ID -> {"product", "publisher", "metric"}
    """
    devices: dict[str, dict[str, str]] = defaultdict(dict)
    for inst in installations:
        if inst["model"]:
            devices[inst["model"]][inst["device"]] = inst["user"]
    rights: dict[str, int] = defaultdict(int)
    for lic in licenses:
        rights[lic["model"]] += int(lic["rights"] or 0)

    rows = []
    for model_id in sorted(set(devices) | set(rights)):
        model = models.get(model_id)
        if model is None:
            continue
        licensed = model_id in rights
        if not licensed and model["metric"] not in (PER_USER, PER_DEVICE):
            continue  # Freeware ohne Lizenz
        users = devices.get(model_id, {}).values()
        if model["metric"] == PER_USER:
            usage = len({u for u in users if u}) + sum(1 for u in users if not u)
        else:
            usage = len(users)
        owned = rights.get(model_id, 0)
        rows.append({
            "product": model["product"],
            "publisher": model["publisher"],
            "metric": model["metric"],
            "rights": owned,
            "usage": usage,
            "difference": owned - usage,
            "status": license_status(licensed, owned, usage),
        })
    return sorted(rows, key=lambda r: (r["difference"], r["product"]))


def expected_rows(ground_truth: dict) -> list[dict]:
    return [{
        "product": e["product"], "publisher": e["publisher"], "metric": METRIC[e["metric"]],
        "rights": e["purchased_rights"], "usage": e["usage"], "difference": e["difference"], "status": e["status"],
    } for e in ground_truth["sam"]]


KEYS = ("metric", "rights", "usage", "difference", "status")


def compare(actual: list[dict], expected: list[dict]) -> dict[str, list[str]]:
    """Produkt -> Liste der Abweichungen (leer = stimmt)."""
    by_product = {r["product"]: r for r in actual}
    result = {}
    for exp in expected:
        act = by_product.get(exp["product"])
        if act is None:
            result[exp["product"]] = ["fehlt"]
            continue
        result[exp["product"]] = [f"{k}: {act[k]} statt {exp[k]}" for k in KEYS if str(act[k]) != str(exp[k])]
    for product in sorted(set(by_product) - {e["product"] for e in expected}):
        result[product] = ["nicht erwartet"]
    return result


def catalog_metrics(path: Path = CATALOG) -> dict[str, str]:
    """Produkt -> Lizenztyp der Plattform; Freeware bekommt ''."""
    with path.open(encoding="utf-8", newline="") as f:
        return {row["product"]: METRIC.get(row["license_metric"], "") for row in csv.DictReader(f)}


def fetch(client: SNClient, api: str) -> dict:
    metrics = catalog_metrics()
    query = f"installed_on.company.name={COMPANY}"
    raw = client.get_records("cmdb_software_instance", query,
                             "software,software.model_id,installed_on,installed_on.assigned_to")
    installations = [{"model": r.get("software.model_id", ""), "device": r["installed_on"],
                      "user": r.get("installed_on.assigned_to", "")} for r in raw]
    lic_raw = client.get_records("alm_license", f"company.name={COMPANY}^install_status!=7^modelISNOTEMPTY",
                                 "asset_tag,model,rights")
    licenses = [{"model": r["model"], "rights": r["rights"]} for r in lic_raw]
    model_ids = sorted({i["model"] for i in installations if i["model"]} | {lic["model"] for lic in licenses})
    models = {}
    for start in range(0, len(model_ids), 100):
        chunk = model_ids[start:start + 100]
        for m in client.get_records("cmdb_software_product_model", "sys_idIN" + ",".join(chunk),
                                    "sys_id,name,manufacturer.name"):
            models[m["sys_id"]] = {"product": m["name"], "publisher": m.get("manufacturer.name", ""),
                                   "metric": metrics.get(m["name"], "")}
    packages = {r["software"] for r in raw}
    try:
        result = client.request("GET", f"{api}/license_position", {"company": COMPANY})["result"]
        stored, calculated_at = result["positions"], result["calculated_at"]
    except SNError as err:
        stored, calculated_at = None, ""
        print(f"  REST API {api} nicht erreichbar: {err}")
    return {"installations": installations, "packages": len(packages), "licenses": lic_raw,
            "models": models, "stored": stored, "calculated_at": calculated_at}


def write_report(data: dict, recomputed: list[dict], expected: list[dict],
                 check_recomputed: dict, check_stored: dict | None, gt_installations: int) -> None:
    stored_ok = check_stored is not None and not any(check_stored.values())
    recomputed_ok = not any(check_recomputed.values())
    matched = sum(1 for v in check_recomputed.values() if not v)
    lines = [
        "# License position",
        "",
        f"Check on {datetime.now():%Y-%m-%d} with `python3 loader/check_license_position.py` (read only).",
        "",
        f"**{matched} of {len(expected)} license positions match the ground truth.** "
        + ("The position calculated by ServiceNow (script include `ItamLicensePosition`, table "
           "`u_itam_license_position`, read via `GET /license_position`) and the independent recalculation "
           "from the raw instance data agree."
           if stored_ok and recomputed_ok else
           "See the deviations below."),
        "",
        "| | |",
        "|---|---|",
        f"| Installations on Muster AG devices | {len(data['installations'])} (ground truth: {gt_installations}) |",
        f"| Software packages in use (raw name + version) | {data['packages']} |",
        f"| Licensed or license-relevant software models | {len(recomputed)} |",
        f"| Licenses (`alm_license`) | {len(data['licenses'])} |",
        "| Position calculated in ServiceNow | "
        + ("matches" if stored_ok else "not readable" if check_stored is None else "deviates")
        + (f" (calculated {data['calculated_at']} UTC)" if data["calculated_at"] else "") + " |",
        "",
        "| Product | Publisher | Metric | Rights | Usage | Difference | Status |",
        "|---|---|---|---:|---:|---:|---|",
    ]
    for r in recomputed:
        lines.append(f"| {r['product']} | {r['publisher']} | {r['metric']} | {r['rights']} | {r['usage']} | "
                     f"{r['difference']:+d} | {STATUS_EN[r['status']]} |")
    deviations = [f"- {p}: {', '.join(v)}" for p, v in check_recomputed.items() if v]
    if check_stored:
        deviations += [f"- stored, {p}: {', '.join(v)}" for p, v in check_stored.items() if v]
    if deviations:
        lines += ["", "Deviations:", "", *deviations]
    lines += [
        "",
        "Counting rules (simplified, same as the generator): *Per workstation* counts devices with at least one "
        "installation; *Per named user* counts distinct assigned users of those devices, a device without a user "
        "counts once. Free software without a license is left out.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    client = SNClient.from_env()
    ground_truth = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))
    expected = expected_rows(ground_truth)
    print(f"Instanz {client.base_url}, Benutzer {client.user}, nur lesend")
    api = load_env().get("SN_ITAM_API", DEFAULT_API)
    data = fetch(client, api)
    recomputed = compute_position(data["installations"], data["licenses"], data["models"])
    check_recomputed = compare(recomputed, expected)
    check_stored = compare(data["stored"], expected) if data["stored"] is not None else None

    print(f"  Installationen {len(data['installations'])} (Wahrheit {ground_truth['counts']['installations']}), "
          f"Pakete {data['packages']}, Lizenzen {len(data['licenses'])}")
    print(f"  {'Produkt':<36} {'Rechte':>6} {'Nutzung':>7} {'Diff':>5}  Status")
    for r in recomputed:
        mark = "ok" if not check_recomputed.get(r["product"]) else "ABWEICHUNG"
        print(f"  {r['product']:<36} {r['rights']:>6} {r['usage']:>7} {r['difference']:>+5}  {r['status']}  {mark}")
    stored_text = ("nicht lesbar" if check_stored is None
                   else "stimmt" if not any(check_stored.values()) else "weicht ab")
    print(f"  Gespeicherte Position in ServiceNow: {stored_text}")

    write_report(data, recomputed, expected, check_recomputed, check_stored, ground_truth["counts"]["installations"])
    print(f"Ergebnis: {REPORT.relative_to(ROOT)}")
    ok = not any(check_recomputed.values()) and check_stored is not None and not any(check_stored.values())
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
