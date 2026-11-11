"""Kleiner REST-Client für ServiceNow (nur Standardbibliothek).

Liest die Zugangsdaten aus der .env im Projektordner. Das Passwort wird nie
ausgegeben oder geloggt.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
RETRY_STATUS = (429, 502, 503, 504)


class SNError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message


def load_env(path: Path = ENV_FILE) -> dict[str, str]:
    """Einfacher .env-Leser: KEY=VALUE je Zeile, # leitet Kommentare ein."""
    if not path.exists():
        raise SystemExit(f"Keine .env gefunden unter {path}")
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()
    return env


class SNClient:
    def __init__(self, base_url: str, user: str, password: str, timeout: int = 120):
        self.base_url = base_url.rstrip("/")
        self.user = user
        self._auth = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
        self.timeout = timeout

    @classmethod
    def from_env(cls, path: Path = ENV_FILE) -> "SNClient":
        env = load_env(path)
        missing = [k for k in ("SN_INSTANCE_URL", "SN_USER", "SN_PASSWORD") if not env.get(k)]
        if missing:
            raise SystemExit(f"In der .env fehlt noch: {', '.join(missing)}")
        return cls(env["SN_INSTANCE_URL"], env["SN_USER"], env["SN_PASSWORD"])

    def request(self, method: str, path: str, params: dict | None = None, body: object = None) -> dict:
        url = self.base_url + path + ("?" + urllib.parse.urlencode(params) if params else "")
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Accept": "application/json", "Authorization": self._auth}
        if data is not None:
            headers["Content-Type"] = "application/json"
        for attempt in range(4):
            req = urllib.request.Request(url, data=data, method=method, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read()
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as err:
                if err.code in RETRY_STATUS and attempt < 3:
                    time.sleep(2 ** attempt)
                    continue
                raise SNError(err.code, _error_message(err)) from None
            except urllib.error.URLError as err:
                if attempt < 3:
                    time.sleep(2 ** attempt)
                    continue
                raise SNError(0, str(err.reason)) from None
        raise SNError(0, "keine Antwort")

    # --- Table API -------------------------------------------------------

    def get_records(self, table: str, query: str = "", fields: str = "", page_size: int = 500) -> list[dict]:
        records, offset = [], 0
        while True:
            params = {
                "sysparm_query": query,
                "sysparm_fields": fields,
                "sysparm_limit": page_size,
                "sysparm_offset": offset,
                "sysparm_exclude_reference_link": "true",
            }
            batch = self.request("GET", f"/api/now/table/{table}", params)["result"]
            records.extend(batch)
            if len(batch) < page_size:
                return records
            offset += page_size

    def create(self, table: str, values: dict) -> dict:
        return self.request("POST", f"/api/now/table/{table}", {"sysparm_exclude_reference_link": "true"}, values)["result"]

    def update(self, table: str, sys_id: str, values: dict) -> dict:
        return self.request("PATCH", f"/api/now/table/{table}/{sys_id}",
                            {"sysparm_exclude_reference_link": "true"}, values)["result"]

    # --- Identification and Reconciliation API ------------------------------

    def identify_reconcile(self, items: list[dict], data_source: str, dry_run: bool = False) -> dict:
        """dry_run=True nutzt den Endpunkt /query: identifiziert nur, schreibt nichts."""
        path = "/api/now/identifyreconcile" + ("/query" if dry_run else "")
        return self.request("POST", path, {"sysparm_data_source": data_source}, {"items": items})


def _error_message(err: urllib.error.HTTPError) -> str:
    try:
        payload = json.load(err)
        error = payload.get("error", {})
        return " ".join(str(error.get(k, "")) for k in ("message", "detail")).strip() or str(payload)[:300]
    except (ValueError, AttributeError):
        return err.reason or ""
