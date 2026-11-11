"""Abbildung der Testdaten auf ServiceNow, ohne Netzwerkzugriff (testbar).

Alle Werte hier sind gegen die PDI (Release Brazil) geprüft, siehe README,
Abschnitt «Befund auf der Entwicklerinstanz».
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

# install_status (Choice-Werte auf cmdb_ci)
INSTALL_STATUS = {
    "Installed": "1",
    "On Order": "2",
    "In Maintenance": "3",
    "Pending Install": "4",
    "Pending Repair": "5",
    "In Stock": "6",
    "Retired": "7",
    "Stolen": "8",
    "Absent": "100",
}

# Quelle in den Testdaten -> IRE-Datenquelle (Choice auf cmdb_ci.discovery_source)
DATA_SOURCES = {
    "Inventar-Export": "MusterInventar",
    "Netzwerk-Scan": "MusterNetzScan",
}
SOURCE_ORDER = ("Inventar-Export", "Netzwerk-Scan")

# Felder, die es nur auf Computer und Server gibt (nicht auf cmdb_ci_hardware,
# Drucker oder Netzwerkgeräten)
COMPUTER_CLASSES = ("cmdb_ci_computer", "cmdb_ci_win_server", "cmdb_ci_linux_server")
COMPUTER_FIELDS = ("os", "os_version", "cpu_core_count", "ram", "disk_space")

PLAIN_FIELDS = ("name", "serial_number", "asset_tag", "ip_address", "mac_address",
                "purchase_date", "warranty_expiration", "cost")

# Spalte in devices.csv -> Art der Referenz
REFERENCE_FIELDS = {
    "company": "company",
    "manufacturer": "manufacturer",
    "model_id": "model",
    "assigned_to": "user",
    "location": "location",
    "department": "department",
}

# Modellkategorie in ServiceNow je Gerätekategorie (steuert die Asset-Erzeugung)
MODEL_CATEGORY = {
    "laptop": "Computer",
    "desktop": "Computer",
    "server": "Server",
    "printer": "Printer",
    "smartphone": "Hardware",
}


def model_category(category: str, manufacturer: str) -> str:
    if category == "network":
        return "Network Gear" if manufacturer == "Fortinet" else "IP Switch"
    return MODEL_CATEGORY[category]


@dataclass
class References:
    """Namen -> sys_id der Stammdaten in der Instanz."""
    company: dict[str, str] = field(default_factory=dict)
    manufacturer: dict[str, str] = field(default_factory=dict)
    model: dict[str, str] = field(default_factory=dict)  # Modellname -> sys_id
    user: dict[str, str] = field(default_factory=dict)  # user_name -> sys_id
    location: dict[str, str] = field(default_factory=dict)
    department: dict[str, str] = field(default_factory=dict)


def build_ire_item(row: dict, refs: References) -> tuple[dict, list[str]]:
    """Baut ein IRE-Item aus einer Zeile von devices.csv.

    Leere Werte werden weggelassen, damit die IRE vorhandene Werte nicht
    überschreibt. Gibt das Item und die Liste nicht auflösbarer Referenzen zurück.
    """
    values: dict[str, str] = {}
    for name in PLAIN_FIELDS:
        if row.get(name, "") != "":
            values[name] = row[name]
    if row["sn_class"] in COMPUTER_CLASSES:
        for name in COMPUTER_FIELDS:
            if row.get(name, "") != "":
                values[name] = row[name]
    if row.get("install_status"):
        values["install_status"] = INSTALL_STATUS[row["install_status"]]

    missing = []
    for column, kind in REFERENCE_FIELDS.items():
        raw = row.get(column, "")
        if not raw:
            continue
        sys_id = getattr(refs, kind).get(raw)
        if sys_id:
            values[column] = sys_id
        else:
            missing.append(f"{column}={raw}")

    item = {
        "className": row["sn_class"],
        "values": values,
        "sys_object_source_info": {
            "source_name": DATA_SOURCES[row["source"]],
            "source_native_key": row["source_id"],
        },
    }
    return item, missing


def parse_ire_response(response: dict) -> list[dict]:
    """Vereinheitlicht die Antwort der IRE (result kann je nach Release ein JSON-String sein)."""
    result = response.get("result", response)
    if isinstance(result, str):
        result = json.loads(result)
    parsed = []
    for item in result.get("items", []):
        errors = item.get("errors") or []
        attempts = item.get("identificationAttempts") or []
        parsed.append({
            "class": item.get("className", ""),
            "operation": item.get("operation", ""),
            "sys_id": item.get("sysId", ""),
            "errors": [str(e.get("message") or e.get("error") or e) for e in errors],
            "identification": [
                f"{a.get('identifierName', '')}/{a.get('attributes', '')}: {a.get('attemptResult', '')}"
                for a in attempts
            ],
        })
    return parsed
