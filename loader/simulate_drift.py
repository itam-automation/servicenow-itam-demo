#!/usr/bin/env python3
"""Demo of module 2: an integration changes the status of two Muster AG CIs.

ServiceNow keeps an asset and its CI in sync when the asset changes; a CI status written
by an integration (discovery, a repair tool) does not flow back to the asset. This script
reproduces that with the loader's integration user (Table API, PATCH on the CI):

    NBZH0001  laptop in use          -> CI «In Stock»       (a scan saw it in the depot)
    NBZH0005  laptop in stock        -> CI «Pending Repair» (the repair tool booked it)

Without --apply it only shows what it would change. Every change is one CI, selected by
name and company, counted first (exactly one match required).

Usage from the project folder:
    python3 loader/simulate_drift.py [--apply]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sn_client import SNClient  # noqa: E402

CHANGES = [("NBZH0001", "6", "scan saw the laptop in the depot"),
           ("NBZH0005", "5", "repair tool booked the laptop")]
LABELS = {"1": "Installed", "5": "Pending Repair", "6": "In Stock", "7": "Retired"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    client = SNClient.from_env()
    for name, status, why in CHANGES:
        query = f"name={name}^company.name=Muster AG"
        if client.count("cmdb_ci_computer", query) != 1:
            print(f"{name}: not exactly one CI, skipped")
            continue
        ci = client.get_records("cmdb_ci_computer", query, "sys_id,name,install_status")[0]
        before = ci["install_status"]
        print(f"{name}: CI {LABELS.get(before, before)} -> {LABELS.get(status, status)} ({why})")
        if args.apply and before != status:
            client.update("cmdb_ci_computer", ci["sys_id"], {"install_status": status})
    if not args.apply:
        print("Dry run; nothing changed (use --apply).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
