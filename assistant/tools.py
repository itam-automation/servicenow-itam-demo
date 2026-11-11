"""Werkzeuge des KI-Assistenten: Definitionen für die Claude API und ihre Ausführung.

Jedes Werkzeug ruft nur ReadOnlyClient auf (nur GET, mit Leitplanken). Fehler
einer Leitplanke gehen als Fehlermeldung an das Modell zurück, damit es die
Abfrage korrigieren kann; an ServiceNow geht in diesem Fall nichts.
"""

from __future__ import annotations

import json

from readonly import ALLOWED, MAX_ROWS, GuardrailError, ReadOnlyClient
from sn_client import SNError

TABLES = sorted(ALLOWED)
FIELD_LIST = "; ".join(f"{t}: {', '.join(f)}" for t, f in sorted(ALLOWED.items()))

TOOLS = [
    {
        "name": "search_records",
        "description": (
            "Liest Datensätze der Muster AG aus einer freigegebenen ServiceNow-Tabelle (nur lesend). "
            "query ist eine ServiceNow Encoded Query ohne Firmenfilter, "
            "z. B. 'install_status=6^model_id.nameLIKEThinkPad' "
            "oder 'warranty_expiration<2027-01-01^ORDERBYwarranty_expiration'. Leerer String = keine Bedingung. "
            "Nur freigegebene Felder in query und fields. Freigegebene Felder: " + FIELD_LIST
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "enum": TABLES},
                "query": {"type": "string", "description": "Encoded Query, leer für alle Datensätze"},
                "fields": {"type": "array", "items": {"type": "string"},
                           "description": "Felder der Antwort; leer = alle freigegebenen Felder"},
                "limit": {"type": "integer", "description": f"höchstens {MAX_ROWS}"},
            },
            "required": ["table", "query", "fields", "limit"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "count_records",
        "description": (
            "Zählt Datensätze der Muster AG in einer freigegebenen Tabelle (nur lesend), optional gruppiert "
            "nach einem freigegebenen Feld, z. B. table='cmdb_ci_hardware', query='', group_by='install_status'. "
            "Für Kennzahlen immer zählen statt Datensätze zu lesen und selbst zu zählen."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "enum": TABLES},
                "query": {"type": "string", "description": "Encoded Query, leer für alle Datensätze"},
                "group_by": {"type": ["string", "null"], "description": "Feld für die Gruppierung oder null"},
            },
            "required": ["table", "query", "group_by"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "get_license_position",
        "description": (
            "Lizenzposition der Muster AG, wie ServiceNow sie berechnet (Script Include ItamLicensePosition): "
            "je lizenzpflichtigem Produkt Lizenztyp, gekaufte Rechte, Nutzung, Differenz und Status "
            "(unterlizenziert, überlizenziert, ausgeglichen, ohne Lizenz, ungenutzt)."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        "strict": True,
    },
]
TOOL_NAMES = {t["name"] for t in TOOLS}


def run_tool(client: ReadOnlyClient, name: str, args: dict) -> tuple[str, bool]:
    """Führt ein Werkzeug aus. Rückgabe: (JSON-Text für das Modell, ist_fehler)."""
    try:
        if name == "search_records":
            rows = client.query(args["table"], args.get("query", ""), args.get("fields") or [],
                                args.get("limit") or 20)
            return json.dumps({"rows": rows, "returned": len(rows)}, ensure_ascii=False), False
        if name == "count_records":
            return json.dumps(client.count(args["table"], args.get("query", ""), args.get("group_by")),
                              ensure_ascii=False), False
        if name == "get_license_position":
            return json.dumps(client.license_position(), ensure_ascii=False), False
        return f"Unbekanntes Werkzeug: {name}", True
    except GuardrailError as err:
        return f"Leitplanke: {err}", True
    except SNError as err:
        return f"ServiceNow-Fehler: {err}", True
    except (KeyError, TypeError, ValueError) as err:
        return f"Ungültige Eingabe: {err}", True
