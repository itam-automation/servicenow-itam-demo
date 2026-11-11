"""Staging-Tabellen und Transform Maps des Imports (eine Quelle für Loader und Einrichtung).

Jede CSV-Datei aus testdata/output hat eine Staging-Tabelle (erbt von
sys_import_set_row) und eine Transform Map. Die Stammdaten werden klassisch
über Feldzuordnungen mit Coalesce geschrieben, die Geräte über ein
onBefore-Skript, das die IRE aufruft (servicenow/device_transform_onbefore.js).
Software, Installationen und Lizenzen (SAM) nutzen Feldzuordnungen, die das
Script Include «MusterSamImport» aufrufen (servicenow/sam_import_utils.js).

    python3 loader/staging.py   # gibt die Spezifikation als JSON aus (für die Einrichtung)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "servicenow"


@dataclass(frozen=True)
class FieldMap:
    source: str  # Spalte der CSV-Datei; in der Staging-Tabelle u_<source>
    target: str
    coalesce: bool = False
    choice_action: str = "ignore"  # für Referenzen: create | ignore | reject
    source_script: str = ""  # Datei in servicenow/
    source_code: str = ""  # oder kurzer Code direkt hier (ruft ein Script Include auf)


@dataclass(frozen=True)
class Staging:
    key: str  # Name der CSV-Datei ohne .csv
    table: str
    label: str
    target: str
    map_name: str
    columns: tuple[str, ...]
    fields: tuple[FieldMap, ...] = ()
    onbefore_script: str = ""  # Datei in servicenow/
    onafter_script: str = ""  # Datei in servicenow/
    oncomplete_script: str = ""  # Datei in servicenow/
    result_columns: tuple[str, ...] = field(default=())  # schreibt das Transformskript


def sam_call(expression: str) -> str:
    """Source Script einer Feldzuordnung, das eine Funktion von «MusterSamImport» aufruft."""
    return f"answer = new MusterSamImport().{expression};"


DEVICE_COLUMNS = (
    "source_id", "source", "category", "sn_class", "name", "serial_number", "asset_tag", "company",
    "manufacturer", "model_id", "os", "os_version", "cpu_core_count", "ram", "disk_space", "ip_address",
    "mac_address", "assigned_to", "location", "department", "install_status", "purchase_date",
    "warranty_expiration", "cost",
)

STAGING = (
    Staging(
        "locations", "u_muster_location_imp", "Muster AG Import Standorte", "cmn_location", "Muster AG Standorte",
        ("name", "street", "zip", "city", "country", "company"),
        (FieldMap("name", "name", coalesce=True), FieldMap("street", "street"), FieldMap("zip", "zip"),
         FieldMap("city", "city"), FieldMap("country", "country"),
         FieldMap("company", "company", choice_action="create")),
    ),
    Staging(
        "departments", "u_muster_department_imp", "Muster AG Import Abteilungen", "cmn_department",
        "Muster AG Abteilungen",
        ("name", "cost_center", "company"),
        (FieldMap("name", "name", coalesce=True), FieldMap("company", "company", coalesce=True),
         FieldMap("cost_center", "id")),
    ),
    Staging(
        "users", "u_muster_user_imp", "Muster AG Import Benutzer", "sys_user", "Muster AG Benutzer",
        ("user_name", "first_name", "last_name", "email", "department", "location", "company", "active"),
        (FieldMap("user_name", "user_name", coalesce=True), FieldMap("first_name", "first_name"),
         FieldMap("last_name", "last_name"), FieldMap("email", "email"), FieldMap("active", "active"),
         FieldMap("department", "department"), FieldMap("location", "location"), FieldMap("company", "company")),
    ),
    Staging(
        "models", "u_muster_model_imp", "Muster AG Import Modelle", "cmdb_hardware_product_model",
        "Muster AG Modelle",
        ("manufacturer", "name", "category"),
        (FieldMap("name", "name", coalesce=True),
         FieldMap("manufacturer", "manufacturer", coalesce=True, choice_action="create"),
         FieldMap("category", "cmdb_model_category", source_script="model_category_source_script.js")),
    ),
    Staging(
        "devices", "u_muster_device_imp", "Muster AG Import Geräte", "cmdb_ci_hardware",
        "Muster AG Geräte -> CMDB (IRE)",
        DEVICE_COLUMNS,
        onbefore_script="device_transform_onbefore.js",
        result_columns=("ire_operation", "ire_ci", "ire_match", "ire_missing", "dq_findings"),
    ),
    Staging(
        "software", "u_muster_software_imp", "Muster AG Import Software", "cmdb_software_product_model",
        "Muster AG Software -> Softwaremodelle",
        ("publisher", "product", "display_name", "versions", "license_metric", "platforms"),
        (FieldMap("product", "name", coalesce=True),
         FieldMap("publisher", "manufacturer", coalesce=True,
                  source_code=sam_call("manufacturer(source.getValue('u_publisher'))")),
         FieldMap("license_metric", "license_type",
                  source_code=sam_call("licenseType(source.getValue('u_license_metric'))"))),
        onafter_script="software_transform_onafter.js",
    ),
    Staging(
        "installations", "u_muster_installation_imp", "Muster AG Import Installationen", "cmdb_software_instance",
        "Muster AG Installationen",
        ("device_source_id", "installed_on", "publisher", "display_name", "version", "install_date"),
        (FieldMap("display_name", "software", coalesce=True,
                  source_code=sam_call("softwarePackage(source.getValue('u_display_name'), "
                                       "source.getValue('u_version'))")),
         FieldMap("installed_on", "installed_on", coalesce=True,
                  source_code=sam_call("device(source.getValue('u_installed_on'))")),
         FieldMap("install_date", "install_date")),
        onbefore_script="installation_transform_onbefore.js",
    ),
    Staging(
        "entitlements", "u_muster_license_imp", "Muster AG Import Lizenzen", "alm_license", "Muster AG Lizenzen",
        ("license_id", "publisher", "product", "metric", "purchased_rights", "unit_cost", "start_date", "end_date"),
        (FieldMap("license_id", "asset_tag", coalesce=True),
         FieldMap("product", "model",
                  source_code=sam_call("softwareModel(source.getValue('u_product'), source.getValue('u_publisher'))")),
         FieldMap("publisher", "company", source_code=sam_call("company()")),
         FieldMap("purchased_rights", "rights"),
         FieldMap("unit_cost", "cost",
                  source_code="answer = parseInt(source.getValue('u_unit_cost'), 10) * "
                              "parseInt(source.getValue('u_purchased_rights'), 10);"),
         FieldMap("start_date", "purchase_date"),
         FieldMap("end_date", "retirement_date")),
        oncomplete_script="license_transform_oncomplete.js",
    ),
)
SAM = ("software", "installations", "entitlements")
BY_KEY = {s.key: s for s in STAGING}


KEY_COLUMN = {"locations": "name", "departments": "name", "users": "user_name", "models": "name",
              "devices": "source_id", "software": "product", "installations": "installed_on",
              "entitlements": "license_id"}


def payload(row: dict, staging: Staging) -> dict[str, str]:
    """Eine CSV-Zeile als Datensatz für insertMultiple der Import Set API.

    insertMultiple ordnet über den Spaltennamen ohne das Präfix u_ zu
    (mit Präfix bleiben die Spalten leer, in der PDI geprüft)."""
    return {column: str(row.get(column, "")) for column in staging.columns}


def read_fields(staging: Staging) -> str:
    """Felder, die nach dem Transform aus der Staging-Tabelle gelesen werden."""
    fields = ["sys_import_state", "sys_target_sys_id", "sys_import_state_comment", "sys_row_error",
              f"u_{KEY_COLUMN[staging.key]}"]
    fields += [f"u_{c}" for c in staging.result_columns]
    return ",".join(fields)


def parse_staging_row(row: dict, staging: Staging) -> dict[str, str]:
    """Ergebnis einer Zeile, wie es nach dem Transform in der Staging-Tabelle steht."""
    parsed = {
        "key": row.get(f"u_{KEY_COLUMN[staging.key]}", ""),
        "status": row.get("sys_import_state", ""),
        "target_sys_id": row.get("sys_target_sys_id", ""),
        "message": row.get("sys_import_state_comment", "") or row.get("sys_row_error", ""),
    }
    for column in staging.result_columns:
        parsed[column] = row.get(f"u_{column}", "")
    return parsed


def script(name: str) -> str:
    return (SCRIPT_DIR / name).read_text(encoding="utf-8") if name else ""


# Script Includes, die die Transform Maps brauchen (Name -> Datei in servicenow/)
SCRIPT_INCLUDES = {"MusterSamImport": "sam_import_utils.js", "ItamLicensePosition": "license_position.js"}


def spec() -> dict:
    """Spezifikation für die Einrichtung in der Instanz (Tabellen, Spalten, Maps, Skripte)."""
    out = []
    for s in STAGING:
        item = asdict(s)
        item["fields"] = [
            {**asdict(f), "source_script": script(f.source_script) or f.source_code}
            for f in s.fields
        ]
        for when in ("onbefore_script", "onafter_script", "oncomplete_script"):
            item[when] = script(getattr(s, when))
        out.append(item)
    return {"staging": out,
            "script_includes": {name: script(file) for name, file in SCRIPT_INCLUDES.items()}}


if __name__ == "__main__":
    print(json.dumps(spec(), ensure_ascii=False))
