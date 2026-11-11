#!/usr/bin/env python3
"""Prüft die Verbindung zur PDI mit dem Integrationsbenutzer aus der .env.

Nur lesende GET-Abfragen, das Passwort wird nie ausgegeben.

Aufruf aus dem Projektordner:
    python3 loader/check_connection.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sn_client import SNClient, SNError  # noqa: E402


def main() -> int:
    client = SNClient.from_env()
    print(f"Instanz: {client.base_url}  Benutzer: {client.user}")
    checks = [
        ("Anmeldung und eigener Benutzer", "sys_user", f"user_name={client.user}", "user_name"),
        ("Lesen CMDB (cmdb_ci_computer)", "cmdb_ci_computer", "", "name"),
    ]
    ok = True
    for label, table, query, fields in checks:
        try:
            result = client.request("GET", f"/api/now/table/{table}",
                                    {"sysparm_query": query, "sysparm_fields": fields, "sysparm_limit": 1})
            print(f"  OK     {label}: {len(result.get('result', []))} Zeile(n)")
        except SNError as err:
            ok = False
            print(f"  FEHLER {label}: {err}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
