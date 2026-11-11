"""Nur lesender Zugriff auf ServiceNow für den KI-Assistenten.

Die Leitplanken stehen im Code, nicht im Prompt:
- Nur HTTP GET. Die Klasse hat keine Methode zum Schreiben, und jede Anfrage
  läuft durch _get, das alles andere als GET ablehnt.
- Nur freigegebene Tabellen und Felder (ALLOWED). Personenbezogene Felder wie
  E-Mail oder Telefon sind nicht dabei.
- Jede Abfrage ist auf die Muster AG beschränkt (SCOPE wird vorangestellt).
- Abfragen werden geprüft: kein serverseitiges Skript (javascript:, gs.), keine
  neue Abfrage (^NQ), kein OR am Anfang (würde die Firma aushebeln), nur
  freigegebene Felder. Hintergrund: ServiceNow ignoriert ungültige
  Abfrageteile stillschweigend und liefert dann zu viele Datensätze.
- Höchstens MAX_ROWS Zeilen je Abfrage.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "loader"))

from sn_client import SNClient  # noqa: E402

COMPANY = "Muster AG"
MAX_ROWS = 100
MAX_QUERY_LENGTH = 500

HARDWARE_FIELDS = (
    "name", "sys_class_name", "asset_tag", "serial_number", "manufacturer", "manufacturer.name", "model_id",
    "model_id.name", "install_status", "assigned_to", "assigned_to.user_name", "assigned_to.name", "location",
    "location.name", "department", "department.name", "purchase_date", "warranty_expiration", "discovery_source",
)
ALLOWED: dict[str, tuple[str, ...]] = {
    "cmdb_ci_hardware": HARDWARE_FIELDS,
    "cmdb_ci_computer": HARDWARE_FIELDS + ("os", "os_version", "ram", "cpu_core_count"),
    "alm_hardware": (
        "asset_tag", "display_name", "model", "model.name", "model_category", "install_status", "substatus",
        "assigned_to", "assigned_to.user_name", "assigned_to.name", "assigned", "location", "location.name", "ci",
        "ci.name", "cost", "warranty_expiration",
    ),
    "cmdb_software_instance": (
        "software", "software.name", "software.version", "software.model_id.name", "installed_on",
        "installed_on.name", "installed_on.assigned_to", "installed_on.assigned_to.user_name", "install_date",
    ),
    "alm_license": (
        "asset_tag", "display_name", "model", "model.name", "rights", "cost", "purchase_date", "retirement_date",
        "install_status",
    ),
    "sys_user": ("user_name", "name", "department", "department.name", "location", "location.name", "active"),
    "cmn_location": ("name", "city", "country"),
    "cmn_department": ("name", "id"),
}
SCOPE = {
    "cmdb_ci_hardware": f"company.name={COMPANY}",
    "cmdb_ci_computer": f"company.name={COMPANY}",
    "alm_hardware": f"ci.company.name={COMPANY}",
    "cmdb_software_instance": f"installed_on.company.name={COMPANY}",
    "alm_license": f"company.name={COMPANY}",
    "sys_user": f"company.name={COMPANY}",
    "cmn_location": f"company.name={COMPANY}",
    "cmn_department": f"company.name={COMPANY}",
}

FORBIDDEN = re.compile(r"javascript\s*:|\bgs\.|glide|\^NQ|\^EQ|sys_scope|\bRLQUERY", re.IGNORECASE)
FIELD = re.compile(r"^(?:OR)?([a-z_][a-z0-9_.]*)")


class GuardrailError(ValueError):
    """Eine Anfrage verletzt eine Leitplanke; sie wird nicht an ServiceNow geschickt."""


def check_table(table: str) -> None:
    if table not in ALLOWED:
        raise GuardrailError(f"Tabelle {table!r} ist nicht freigegeben. Erlaubt: {', '.join(sorted(ALLOWED))}")


def check_fields(table: str, fields: list[str]) -> list[str]:
    check_table(table)
    if not fields:
        return list(ALLOWED[table])
    unknown = [f for f in fields if f not in ALLOWED[table]]
    if unknown:
        raise GuardrailError(f"Felder nicht freigegeben für {table}: {', '.join(unknown)}. "
                             f"Erlaubt: {', '.join(ALLOWED[table])}")
    return list(fields)


def check_query(table: str, query: str) -> str:
    """Prüft eine Encoded Query und stellt die Firmen-Einschränkung voran."""
    check_table(table)
    query = (query or "").strip().strip("^")
    if len(query) > MAX_QUERY_LENGTH:
        raise GuardrailError(f"Abfrage länger als {MAX_QUERY_LENGTH} Zeichen")
    if FORBIDDEN.search(query):
        raise GuardrailError("Abfrage enthält einen nicht erlaubten Teil (Skript, ^NQ, ^EQ oder RLQUERY)")
    for i, part in enumerate(p for p in query.split("^") if p):
        if part.startswith("ORDERBY"):
            field = part.removeprefix("ORDERBYDESC").removeprefix("ORDERBY")
        else:
            if i == 0 and part.startswith("OR"):
                raise GuardrailError("Eine Abfrage darf nicht mit OR beginnen "
                                     "(würde die Firmen-Einschränkung aufheben)")
            match = FIELD.match(part)
            if not match:
                raise GuardrailError(f"Bedingung nicht lesbar: {part!r}")
            field = match.group(1)  # Operatoren sind gross geschrieben und gehören nicht dazu
        if field not in ALLOWED[table]:
            raise GuardrailError(f"Feld {field!r} ist für {table} nicht freigegeben "
                                 "(ServiceNow würde ein unbekanntes Feld stillschweigend ignorieren)")
    return SCOPE[table] + (f"^{query}" if query else "")


class ReadOnlyClient:
    """Lesender Zugriff mit Leitplanken; schreibt nie."""

    def __init__(self, client: SNClient, itam_api: str):
        self._client = client
        self._itam_api = itam_api
        self.calls: list[dict] = []  # Protokoll aller Anfragen dieses Laufs

    @property
    def user(self) -> str:
        return self._client.user

    def _get(self, path: str, params: dict) -> dict:
        self.calls.append({"method": "GET", "path": path, "params": params})
        return self._client.request("GET", path, params)

    def query(self, table: str, query: str = "", fields: list[str] | None = None, limit: int = 20) -> list[dict]:
        chosen = check_fields(table, fields or [])
        full_query = check_query(table, query)
        limit = max(1, min(int(limit), MAX_ROWS))
        result = self._get(f"/api/now/table/{table}", {
            "sysparm_query": full_query,
            "sysparm_fields": ",".join(chosen),
            "sysparm_limit": limit,
            "sysparm_display_value": "true",
            "sysparm_exclude_reference_link": "true",
        })
        return result.get("result", [])

    def count(self, table: str, query: str = "", group_by: str | None = None) -> dict:
        full_query = check_query(table, query)
        params = {"sysparm_count": "true", "sysparm_query": full_query, "sysparm_display_value": "true"}
        if group_by:
            check_fields(table, [group_by])
            params["sysparm_group_by"] = group_by
        result = self._get(f"/api/now/stats/{table}", params)["result"]
        if not group_by:
            return {"count": int(result["stats"]["count"])}
        groups = []
        for row in result:
            value = row["groupby_fields"][0]
            groups.append({"value": value.get("display_value") or value.get("value") or "(leer)",
                           "count": int(row["stats"]["count"])})
        return {"groups": sorted(groups, key=lambda g: -g["count"])}

    def license_position(self) -> dict:
        return self._get(f"{self._itam_api}/license_position", {"company": COMPANY})["result"]
