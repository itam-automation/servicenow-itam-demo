#!/usr/bin/env python3
"""Testdaten-Generator für die ServiceNow-ITAM-Demo.

Erzeugt erfundene Daten für die fiktive Firma «Muster AG»: Standorte,
Abteilungen, Benutzer, Modelle, rund 200 Geräte, Softwareprodukte,
Installationen und Lizenzrechte. Ausgabe als CSV (UTF-8) plus
ground_truth.json.

- Alle Namen, Seriennummern und Adressen sind frei erfunden. Die E-Mail-Domain
  muster.example nutzt die nach RFC 2606 reservierte Endung .example,
  MAC-Adressen liegen im lokal verwalteten Bereich (02:...), IP-Adressen im
  privaten Netz 10.0.0.0/8. Hersteller- und Produktnamen sind echt, damit die
  Normalisierung in ServiceNow realistisch bleibt.
- Bewusst eingebaute Datenqualitätsfehler und Dubletten stehen in
  ground_truth.json. So lässt sich später prüfen, ob die Reports in ServiceNow
  genau diese Fehler finden.
- Spaltennamen folgen den Feldnamen in ServiceNow. Felder, CMDB-Klassen
  (Spalte sn_class), Statuswerte und Herstellernamen sind gegen die PDI
  (Release Brazil) geprüft. Alle Geräte tragen company = Muster AG, damit
  Reports sie von den Demo-Daten der PDI trennen.
- Lizenzmetriken und Preise sind vereinfacht und fiktiv.
- Nur Standardbibliothek. Gleicher Seed und gleicher Stichtag ergeben
  byte-genau dieselben Dateien.

Aufruf:
    python3 testdata/generate_testdata.py
    python3 testdata/generate_testdata.py --seed 7 --count 300 --out /pfad/zum/ordner
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

COMPANY = "Muster AG"
DOMAIN = "muster.example"

DEFAULT_SEED = 42
DEFAULT_COUNT = 200
MIN_COUNT = 50
DEFAULT_REFERENCE_DATE = date(2026, 11, 11)
FLEET_START = date(2020, 1, 1)
OUTPUT_DIR = Path(__file__).resolve().parent / "output"

SOURCE_INVENTORY = "Inventar-Export"
SOURCE_SCAN = "Netzwerk-Scan"

# Statuswerte wie in der ServiceNow-Oberfläche (Feld install_status).
# Die numerischen Werte ordnet erst der Loader zu, nach Prüfung auf der Instanz.
INSTALLED = "Installed"
IN_STOCK = "In Stock"
IN_MAINTENANCE = "In Maintenance"
RETIRED = "Retired"
IN_USE = (INSTALLED, IN_MAINTENANCE)

ENDPOINTS = ("laptop", "desktop", "smartphone")
COMPUTERS = ("laptop", "desktop")

TABLES = (
    "locations",
    "departments",
    "users",
    "models",
    "devices",
    "software",
    "installations",
    "entitlements",
)

# --------------------------------------------------------------- Stammdaten

LOCATIONS = [
    # Kürzel, Name, Strasse, PLZ, Ort, Anteil Mitarbeitende
    ("ZH", "Muster AG Zürich", "Musterstrasse 10", "8005", "Zürich", 0.45),
    ("BE", "Muster AG Bern", "Beispielweg 3", "3011", "Bern", 0.20),
    ("BS", "Muster AG Basel", "Musterplatz 7", "4051", "Basel", 0.15),
    ("LU", "Muster AG Luzern", "Beispielgasse 21", "6003", "Luzern", 0.10),
    ("WI", "Muster AG Winterthur", "Musterallee 5", "8400", "Winterthur", 0.10),
]

DEPARTMENTS = [
    # Name, Kostenstelle, Anteil Mitarbeitende
    ("Geschäftsleitung", "KS-1000", 0.05),
    ("Finanzen", "KS-2000", 0.12),
    ("Personal", "KS-2100", 0.07),
    ("Informatik", "KS-3000", 0.13),
    ("Vertrieb", "KS-4000", 0.20),
    ("Marketing", "KS-4100", 0.10),
    ("Einkauf", "KS-5000", 0.08),
    ("Technik", "KS-6000", 0.15),
    ("Kundendienst", "KS-7000", 0.10),
]

FIRST_NAMES = [
    "Anna", "Lea", "Laura", "Sarah", "Julia", "Nina", "Sandra", "Andrea",
    "Claudia", "Monika", "Sophie", "Mia", "Elena", "Martina", "Nadine", "Selina",
    "Lukas", "Noah", "David", "Daniel", "Thomas", "Michael", "Marco", "Stefan",
    "Reto", "Simon", "Patrick", "Andreas", "Beat", "Urs", "Jonas", "Fabian",
]

LAST_NAMES = [
    "Müller", "Meier", "Schmid", "Keller", "Weber", "Huber", "Schneider", "Meyer",
    "Steiner", "Fischer", "Gerber", "Brunner", "Baumann", "Frei", "Zimmermann",
    "Moser", "Widmer", "Wyss", "Graf", "Roth", "Suter", "Baumgartner", "Bachmann",
    "Kälin", "Lüthi", "Studer", "Bühler", "Hofer", "Arnold", "Marti",
]


# Normschreibweise der Hersteller = Namen, die in der PDI (Release Brazil) bereits
# als Hersteller in core_company stehen (geprüft am 11.11.2026). So lösen sich die
# Referenzen auf, und nur die bewusst eingebauten Varianten fallen auf.
# Fortinet und Hewlett Packard Enterprise fehlen dort und werden beim Laden angelegt.
DELL = "Dell Inc."
HP = "Hewlett-Packard"
HPE = "Hewlett Packard Enterprise"


@dataclass(frozen=True)
class Model:
    manufacturer: str
    name: str
    category: str
    year_from: int  # Beschaffung möglich ab Jahr
    year_to: int  # bis Jahr
    price_min: int  # CHF, fiktiv
    price_max: int


MODELS = [
    # Laptops
    Model(DELL, "Latitude 5410", "laptop", 2020, 2021, 1100, 1500),
    Model(DELL, "Latitude 5420", "laptop", 2021, 2022, 1150, 1550),
    Model(DELL, "Latitude 5440", "laptop", 2023, 2024, 1200, 1600),
    Model(DELL, "Latitude 5450", "laptop", 2024, 2026, 1250, 1650),
    Model("Lenovo", "ThinkPad T14 Gen 1", "laptop", 2020, 2021, 1100, 1500),
    Model("Lenovo", "ThinkPad T14 Gen 3", "laptop", 2022, 2023, 1200, 1600),
    Model("Lenovo", "ThinkPad T14 Gen 5", "laptop", 2024, 2026, 1300, 1700),
    Model("Lenovo", "ThinkPad X1 Carbon Gen 11", "laptop", 2023, 2026, 1900, 2400),
    Model(HP, "EliteBook 840 G8", "laptop", 2021, 2022, 1200, 1600),
    Model(HP, "EliteBook 840 G10", "laptop", 2023, 2025, 1300, 1700),
    Model("Apple", "MacBook Pro 14 (M3)", "laptop", 2023, 2024, 2200, 2800),
    Model("Apple", "MacBook Pro 14 (M4)", "laptop", 2024, 2026, 2200, 2800),
    # Desktops
    Model(DELL, "OptiPlex 7080", "desktop", 2020, 2021, 800, 1100),
    Model(DELL, "OptiPlex 7090", "desktop", 2021, 2022, 850, 1150),
    Model(DELL, "OptiPlex 7010", "desktop", 2023, 2026, 900, 1200),
    Model(HP, "Elite Mini 800 G9", "desktop", 2022, 2024, 900, 1200),
    Model("Lenovo", "ThinkCentre M70q Gen 4", "desktop", 2023, 2026, 800, 1100),
    # Server
    Model(DELL, "PowerEdge R640", "server", 2020, 2021, 9000, 14000),
    Model(DELL, "PowerEdge R650", "server", 2021, 2023, 10000, 15000),
    Model(DELL, "PowerEdge R660", "server", 2023, 2026, 11000, 16000),
    Model(HPE, "ProLiant DL380 Gen10 Plus", "server", 2021, 2024, 10000, 15000),
    Model(HPE, "ProLiant DL380 Gen11", "server", 2023, 2026, 11000, 16000),
    Model("Lenovo", "ThinkSystem SR650 V2", "server", 2021, 2023, 9500, 14500),
    # Drucker
    Model(HP, "Color LaserJet Enterprise M555", "printer", 2020, 2024, 900, 1300),
    Model(HP, "Color LaserJet Enterprise 5700", "printer", 2023, 2026, 1000, 1400),
    Model("Brother", "HL-L8360CDW", "printer", 2020, 2026, 500, 700),
    # Netzwerk
    Model("Cisco", "Catalyst 9200L-48P-4G", "network", 2020, 2026, 3000, 4500),
    Model("Cisco", "Catalyst 9300-48P", "network", 2020, 2026, 6000, 9000),
    Model("Fortinet", "FortiGate 60F", "network", 2020, 2026, 800, 1200),
    # Smartphones
    Model("Apple", "iPhone 12", "smartphone", 2020, 2021, 700, 900),
    Model("Apple", "iPhone 13", "smartphone", 2021, 2022, 700, 900),
    Model("Apple", "iPhone 15", "smartphone", 2023, 2024, 750, 950),
    Model("Apple", "iPhone 16", "smartphone", 2024, 2026, 800, 1000),
    Model("Samsung", "Galaxy S21", "smartphone", 2021, 2022, 650, 850),
    Model("Samsung", "Galaxy S23", "smartphone", 2023, 2024, 700, 900),
    Model("Samsung", "Galaxy S24", "smartphone", 2024, 2026, 750, 950),
]

# Kategorie: (Anteil am Bestand, Garantiejahre zur Auswahl, Nutzungsdauer in Jahren)
CATEGORIES = {
    "laptop": (0.55, (3, 3, 3, 4, 5), 5),
    "desktop": (0.175, (3, 3, 5), 5),
    "server": (0.09, (5,), 7),
    "printer": (0.05, (3,), 7),
    "network": (0.075, (5,), 7),
    "smartphone": (0.06, (2,), 4),
}

# Verteilung der Infrastruktur auf Standorte (ZH, BE, BS, LU, WI)
INFRA_LOCATION_WEIGHTS = {
    "server": (0.8, 0.2, 0, 0, 0),
    "network": (0.4, 0.15, 0.15, 0.15, 0.15),
    "printer": (0.4, 0.2, 0.2, 0.1, 0.1),
}

# Seriennummern: Präfix und Anzahl zufälliger Zeichen je Hersteller
SERIAL_FORMATS = {
    DELL: ("", 7),
    "Lenovo": ("PF", 6),
    HP: ("5CG", 7),
    HPE: ("CZ", 8),
    "Apple": ("", 10),
    "Cisco": ("FOC", 8),
    "Fortinet": ("FGT60F", 8),
    "Brother": ("E7", 8),
    "Samsung": ("R5C", 8),
}
SERIAL_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ0123456789"

# Abweichende Schreibweisen, wie sie aus verschiedenen Quellen kommen
MANUFACTURER_VARIANTS = {
    DELL: ("Dell", "DELL"),
    HP: ("HP", "HP Inc.", "hp"),
    "Lenovo": ("LENOVO", "Lenovo Group Ltd."),
    "Apple": ("Apple Inc.",),
    "Cisco": ("Cisco Systems, Inc.",),
}

# Kerne, RAM in MB, Disk in GB
HARDWARE = {
    "laptop": ((8, 10, 12), (16384, 32768), (512, 1024)),
    "desktop": ((6, 8, 12), (16384, 32768), (512, 1024)),
    "server": ((16, 24, 32), (131072, 262144), (1920, 3840)),
}

SERVER_ROLES = ("APP", "DB", "FILE", "WEB", "DC", "BKP")
NAME_PREFIX = {"laptop": "NB", "desktop": "PC", "printer": "PRT", "smartphone": "MOB"}
SUBNET = {"network": 0, "server": 10, "laptop": 20, "desktop": 20, "printer": 30}


@dataclass(frozen=True)
class Software:
    publisher: str
    product: str  # normalisierter Produktname, auf den sich Lizenzen beziehen
    display_name: str  # Rohname, wie ihn ein Inventar-Tool meldet
    versions: tuple[str, ...]
    license_metric: str  # Free, Per Device, Per User (vereinfacht)
    platforms: tuple[str, ...] = ("win",)


SOFTWARE = [
    Software("Microsoft", "Microsoft 365 Apps for enterprise", "Microsoft 365 Apps for enterprise - de-de",
             ("16.0.17928.20156", "16.0.18129.20116"), "Per User", ("win", "mac")),
    Software("Microsoft", "Visio Plan 2", "Microsoft Visio - de-de", ("16.0.18129.20116",), "Per User"),
    Software("Microsoft", "Project Professional 2021", "Microsoft Project Professional 2021 - de-de",
             ("16.0.14332.20763",), "Per Device"),
    Software("Microsoft", "Power BI Desktop", "Microsoft PowerBI Desktop (x64)", ("2.137.952.0",), "Free"),
    Software("Microsoft", "Visual Studio Code", "Microsoft Visual Studio Code", ("1.95.2",), "Free", ("win", "mac")),
    Software("Microsoft", "SQL Server Management Studio", "SQL Server Management Studio", ("20.2.30.0",), "Free"),
    Software("Adobe", "Acrobat Pro", "Adobe Acrobat Pro (64-bit)", ("24.004.20220",), "Per User", ("win", "mac")),
    Software("Adobe", "Acrobat Reader", "Adobe Acrobat Reader (64-bit)", ("24.003.20180", "24.004.20220"),
             "Free", ("win", "mac")),
    Software("Adobe", "Photoshop", "Adobe Photoshop 2025", ("26.1.0",), "Per User", ("win", "mac")),
    Software("Autodesk", "AutoCAD LT", "AutoCAD LT 2025 - Deutsch (German)", ("25.0.58.0",), "Per User"),
    Software("TechSmith", "Snagit", "Snagit 2024", ("24.2.0",), "Per User", ("win", "mac")),
    Software("JetBrains", "PyCharm Professional", "PyCharm 2024.3", ("2024.3",), "Per User", ("win", "mac")),
    Software("win.rar GmbH", "WinRAR", "WinRAR (64-bit)", ("6.24", "7.01"), "Per Device"),
    Software("Google", "Chrome", "Google Chrome", ("130.0.6723.117", "131.0.6778.86"), "Free", ("win", "mac")),
    Software("Mozilla", "Firefox", "Mozilla Firefox (x64 de)", ("132.0.2",), "Free", ("win", "mac")),
    Software("Igor Pavlov", "7-Zip", "7-Zip (x64)", ("23.01", "24.08"), "Free"),
    Software("Notepad++ Team", "Notepad++", "Notepad++ (64-bit x64)", ("8.7",), "Free"),
    Software("Python Software Foundation", "Python", "Python 3.12 (64-bit)", ("3.12.7",), "Free", ("win", "mac")),
    Software("The Git Development Community", "Git", "Git", ("2.47.0",), "Free", ("win", "mac")),
    Software("Zoom Video Communications, Inc.", "Zoom Workplace", "Zoom Workplace (64-bit)", ("6.2.7",),
             "Free", ("win", "mac")),
    Software("SAP SE", "SAP GUI for Windows", "SAP GUI for Windows 8.00", ("8.00",), "Free"),
    Software("KeePassXC Team", "KeePassXC", "KeePassXC", ("2.7.9",), "Free", ("win", "mac")),
]

# Wahrscheinlichkeit einer Installation je Produkt
SOFTWARE_BASELINE = {
    "Microsoft 365 Apps for enterprise": 0.97,
    "Chrome": 0.90,
    "Acrobat Reader": 0.85,
    "7-Zip": 0.70,
    "Zoom Workplace": 0.60,
}
SOFTWARE_RANDOM_EXTRAS = {
    "WinRAR": 0.10,
    "Firefox": 0.15,
    "Notepad++": 0.08,
    "Snagit": 0.03,
    "KeePassXC": 0.05,
}
SOFTWARE_BY_DEPARTMENT = {
    "Informatik": {
        "Visual Studio Code": 0.9, "Python": 0.7, "Git": 0.8, "Notepad++": 0.8, "KeePassXC": 0.7,
        "SQL Server Management Studio": 0.5, "PyCharm Professional": 0.4, "Firefox": 0.6,
        "Visio Plan 2": 0.4, "Power BI Desktop": 0.3,
    },
    "Technik": {"AutoCAD LT": 0.6, "Visio Plan 2": 0.3, "Project Professional 2021": 0.3},
    "Marketing": {"Photoshop": 0.6, "Acrobat Pro": 0.7, "Snagit": 0.5},
    "Finanzen": {"Acrobat Pro": 0.4, "SAP GUI for Windows": 0.9, "Power BI Desktop": 0.5},
    "Einkauf": {"SAP GUI for Windows": 0.9, "Acrobat Pro": 0.2},
    "Vertrieb": {"Power BI Desktop": 0.3, "Acrobat Pro": 0.2},
    "Geschäftsleitung": {"Acrobat Pro": 0.5, "Power BI Desktop": 0.4, "Project Professional 2021": 0.2},
    "Personal": {"Acrobat Pro": 0.3},
    "Kundendienst": {"Snagit": 0.2},
}

# Lizenzplan: Produkt -> (gekaufte Rechte minus Nutzung, Stückpreis CHF fiktiv, Jahresabo)
# Produkte mit Lizenzpflicht ohne Eintrag (hier WinRAR) haben bewusst keine Lizenz.
LICENSE_PLAN = {
    "Microsoft 365 Apps for enterprise": (5, 150, True),
    "Visio Plan 2": (-2, 180, True),
    "Project Professional 2021": (0, 1100, False),
    "Acrobat Pro": (-4, 240, True),
    "Photoshop": (3, 400, True),
    "AutoCAD LT": (0, 550, True),
    "Snagit": (2, 70, False),
    "PyCharm Professional": (-1, 260, True),
}

# Anteil eingebauter Fehler, bezogen auf die Anzahl Geräte
ISSUE_RATES = {
    "assigned_to_inactive_user": 0.02,
    "installed_without_user": 0.025,
    "retired_with_user": 0.015,
    "missing_serial_number": 0.04,
    "missing_location": 0.03,
    "manufacturer_name_variant": 0.075,
    "duplicate_same_serial": 0.03,
    "duplicate_serial_variant": 0.015,
    "duplicate_same_name_no_serial": 0.015,
}

ISSUE_TYPES = {
    "assigned_to_inactive_user": "Gerät in Betrieb, der zugewiesene Benutzer ist inaktiv (Austritt nicht verarbeitet)",
    "installed_without_user": "Endgerät in Betrieb ohne zugewiesenen Benutzer",
    "retired_with_user": "Ausgemustertes Endgerät ist noch einem Benutzer zugewiesen",
    "missing_serial_number": "Seriennummer fehlt",
    "missing_location": "Standort fehlt",
    "manufacturer_name_variant": "Herstellername weicht von der Normschreibweise ab",
    "duplicate_same_serial": "Dublette aus dem Netzwerk-Scan: gleiche Seriennummer, Name als FQDN",
    "duplicate_serial_variant": "Dublette aus dem Netzwerk-Scan: Seriennummer in anderer Schreibweise, Name als FQDN, andere MAC",
    "duplicate_same_name_no_serial": "Dublette aus dem Netzwerk-Scan: gleicher Name, keine Seriennummer",
}


# -------------------------------------------------------------- Hilfsfunktionen

def to_ascii(text: str) -> str:
    """Umlaute für Benutzernamen und E-Mail-Adressen umschreiben."""
    for src, dst in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("Ä", "Ae"), ("Ö", "Oe"), ("Ü", "Ue")):
        text = text.replace(src, dst)
    return text


def random_date(rng: random.Random, start: date, end: date) -> date:
    return start + timedelta(days=rng.randint(0, (end - start).days))


def add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29. Februar
        return d.replace(year=d.year + years, day=28)


def new_serial(rng: random.Random, manufacturer: str, taken: set[str]) -> str:
    prefix, length = SERIAL_FORMATS[manufacturer]
    while True:
        serial = prefix + "".join(rng.choice(SERIAL_CHARS) for _ in range(length))
        if serial not in taken:
            taken.add(serial)
            return serial


def new_mac(rng: random.Random, taken: set[str]) -> str:
    while True:
        mac = "02:" + ":".join(f"{rng.randrange(256):02X}" for _ in range(5))
        if mac not in taken:
            taken.add(mac)
            return mac


def category_counts(count: int) -> dict[str, int]:
    counts = {cat: round(count * spec[0]) for cat, spec in CATEGORIES.items()}
    counts["laptop"] += count - sum(counts.values())
    return counts


def pick_status(rng: random.Random, category: str, purchase: date, ref: date) -> str:
    age_years = (ref - purchase).days / 365.25
    lifetime = CATEGORIES[category][2]
    if age_years > lifetime and rng.random() < 0.85:
        return RETIRED
    if category in ENDPOINTS and age_years < 0.25 and rng.random() < 0.5:
        return IN_STOCK
    r = rng.random()
    if r < 0.03:
        return IN_MAINTENANCE
    # Lagerbestand, damit der Bestellprozess (Baustein 3) Geräte zuweisen kann
    if r < 0.12 and category in ENDPOINTS:
        return IN_STOCK
    return INSTALLED


def pick_os(rng: random.Random, category: str, manufacturer: str, purchase: date) -> tuple[str, str]:
    if category in COMPUTERS:
        if manufacturer == "Apple":
            return "macOS", rng.choice(["14 Sonoma", "15 Sequoia"])
        if purchase.year <= 2021 and rng.random() < 0.35:
            return "Windows 10 Enterprise", "22H2"
        return "Windows 11 Enterprise", rng.choice(["23H2", "24H2", "24H2"])
    if category == "server":
        return rng.choices(
            [
                ("Windows Server 2022 Standard", "21H2"),
                ("Windows Server 2019 Standard", "1809"),
                ("Red Hat Enterprise Linux", "9.4"),
                ("Ubuntu", "22.04 LTS"),
            ],
            weights=[5, 2, 2, 1],
        )[0]
    if category == "smartphone":
        return ("iOS", "18.1") if manufacturer == "Apple" else ("Android", "14")
    return "", ""


def pick_hardware(rng: random.Random, category: str) -> tuple:
    if category not in HARDWARE:
        return "", "", ""
    cores, ram, disk = HARDWARE[category]
    return rng.choice(cores), rng.choice(ram), rng.choice(disk)


def sn_class(category: str, manufacturer: str, os_name: str) -> str:
    """CMDB-Klasse, gegen die PDI geprüft (11.11.2026). Für Smartphones hat die
    Basis-CMDB keine eigene Klasse; cmdb_ci_comm hätte keine IRE-Regel, deshalb
    die generische Klasse cmdb_ci_hardware (Hardware Rule greift)."""
    if category in COMPUTERS:
        return "cmdb_ci_computer"
    if category == "server":
        return "cmdb_ci_win_server" if os_name.startswith("Windows") else "cmdb_ci_linux_server"
    if category == "printer":
        return "cmdb_ci_printer"
    if category == "network":
        return "cmdb_ci_ip_firewall" if manufacturer == "Fortinet" else "cmdb_ci_ip_switch"
    return "cmdb_ci_hardware"


def host_name(rng: random.Random, category: str, manufacturer: str, loc_code: str, counters: Counter) -> str:
    if category == "server":
        key = f"SRV{loc_code}{rng.choice(SERVER_ROLES)}"
        counters[key] += 1
        return f"{key}{counters[key]:02d}"
    if category == "network":
        prefix = "FW" if manufacturer == "Fortinet" else "SW"
    else:
        prefix = NAME_PREFIX[category]
    key = f"{prefix}{loc_code}"
    counters[key] += 1
    width = 4 if category in ENDPOINTS else 2
    return f"{key}{counters[key]:0{width}d}"


def new_ip(category: str, loc_index: int, counters: Counter) -> str:
    if category not in SUBNET:
        return ""
    key = (SUBNET[category], loc_index)
    counters[key] += 1
    return f"10.{SUBNET[category]}.{loc_index}.{counters[key] + 9}"


# ------------------------------------------------------------------ Stammdaten

def make_locations() -> list[dict]:
    return [
        {"name": name, "street": street, "zip": zip_code, "city": city, "country": "Switzerland", "company": COMPANY}
        for _, name, street, zip_code, city, _ in LOCATIONS
    ]


def make_departments() -> list[dict]:
    return [{"name": name, "cost_center": cost_center, "company": COMPANY} for name, cost_center, _ in DEPARTMENTS]


def make_users(rng: random.Random, count: int) -> list[dict]:
    users = []
    taken: set[str] = set()
    for _ in range(count):
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(LAST_NAMES)
        base = f"{to_ascii(first)}.{to_ascii(last)}".lower()
        user_name, n = base, 2
        while user_name in taken:
            user_name, n = f"{base}{n}", n + 1
        taken.add(user_name)
        department = rng.choices(DEPARTMENTS, weights=[d[2] for d in DEPARTMENTS])[0][0]
        location = rng.choices(LOCATIONS, weights=[loc[5] for loc in LOCATIONS])[0][1]
        users.append({
            "user_name": user_name,
            "first_name": first,
            "last_name": last,
            "email": f"{user_name}@{DOMAIN}",
            "department": department,
            "location": location,
            "company": COMPANY,
            "active": "true",
        })
    return users


def make_models() -> list[dict]:
    return [{"manufacturer": m.manufacturer, "name": m.name, "category": m.category} for m in MODELS]


# ---------------------------------------------------------------------- Geräte

def make_devices(rng: random.Random, count: int, ref: date, users: list[dict]) -> list[dict]:
    loc_codes = [loc[0] for loc in LOCATIONS]
    loc_name = {loc[0]: loc[1] for loc in LOCATIONS}
    loc_code_by_name = {loc[1]: loc[0] for loc in LOCATIONS}
    loc_weights = [loc[5] for loc in LOCATIONS]

    free_users = users[:]
    rng.shuffle(free_users)

    serials: set[str] = set()
    macs: set[str] = set()
    name_counters: Counter = Counter()
    ip_counters: Counter = Counter()
    devices = []
    seq = 0

    for category, n in category_counts(count).items():
        _, warranty_choices, _ = CATEGORIES[category]
        for _ in range(n):
            purchase = random_date(rng, FLEET_START, ref - timedelta(days=14))
            model = rng.choice([
                m for m in MODELS
                if m.category == category and m.year_from <= purchase.year <= m.year_to
            ])
            status = pick_status(rng, category, purchase, ref)

            user = None
            if category in COMPUTERS and status in IN_USE:
                user = free_users.pop() if free_users else rng.choice(users)
            elif category == "smartphone" and status in IN_USE:
                user = rng.choice(users)

            if user:
                loc_code = loc_code_by_name[user["location"]]
                department = user["department"]
            elif category in ENDPOINTS:
                loc_code = "ZH"  # Lager und Entsorgung laufen über den Hauptsitz
                department = ""
            else:
                loc_code = rng.choices(loc_codes, weights=INFRA_LOCATION_WEIGHTS[category])[0]
                department = "Informatik"

            os_name, os_version = pick_os(rng, category, model.manufacturer, purchase)
            cores, ram, disk = pick_hardware(rng, category)
            seq += 1
            devices.append({
                "source_id": f"INV-{seq:05d}",
                "source": SOURCE_INVENTORY,
                "category": category,
                "sn_class": sn_class(category, model.manufacturer, os_name),
                "name": host_name(rng, category, model.manufacturer, loc_code, name_counters),
                "serial_number": new_serial(rng, model.manufacturer, serials),
                "asset_tag": f"MA-{seq:06d}",
                "company": COMPANY,  # trennt die Testdaten von den Demo-Daten der PDI
                "manufacturer": model.manufacturer,
                "model_id": model.name,
                "os": os_name,
                "os_version": os_version,
                "cpu_core_count": cores,
                "ram": ram,
                "disk_space": disk,
                "ip_address": new_ip(category, loc_codes.index(loc_code), ip_counters) if status in IN_USE else "",
                "mac_address": new_mac(rng, macs),
                "assigned_to": user["user_name"] if user else "",
                "location": loc_name[loc_code],
                "department": department,
                "install_status": status,
                "purchase_date": purchase.isoformat(),
                "warranty_expiration": add_years(purchase, rng.choice(warranty_choices)).isoformat(),
                "cost": rng.randrange(model.price_min, model.price_max + 1, 10),
            })
    return devices


def scan_copy(original: dict, seq: int, name: str, serial: str) -> dict:
    """Datensatz, wie ihn ein Netzwerk-Scan liefern würde: technische Felder ja,
    kaufmännische und organisatorische Felder nein."""
    row = {key: "" for key in original}
    row.update({
        "source_id": f"SCAN-{seq:04d}",
        "source": SOURCE_SCAN,
        "category": original["category"],
        "sn_class": original["sn_class"],
        "name": name,
        "serial_number": serial,
        "company": original["company"],  # der Scan läuft im Netz der Muster AG
        "manufacturer": original["manufacturer"],
        "model_id": original["model_id"],
        "os": original["os"],
        "os_version": original["os_version"],
        "cpu_core_count": original["cpu_core_count"],
        "ram": original["ram"],
        "disk_space": original["disk_space"],
        "ip_address": original["ip_address"],
        "mac_address": original["mac_address"],
        "install_status": INSTALLED,
    })
    return row


def inject_issues(rng: random.Random, devices: list[dict], users: list[dict]) -> tuple[list[dict], list[dict]]:
    """Baut bewusst Fehler ein. Jedes Gerät bekommt höchstens einen Fehler,
    damit die erwarteten Zahlen eindeutig bleiben. Gibt (Dubletten, Fehlerliste) zurück."""
    count = len(devices)
    users_by_name = {u["user_name"]: u for u in users}
    used: set[str] = set()
    issues: list[dict] = []

    def k(kind: str) -> int:
        return max(1, round(count * ISSUE_RATES[kind]))

    def pick(candidates: list[dict], n: int) -> list[dict]:
        pool = [d for d in candidates if d["source_id"] not in used]
        chosen = rng.sample(pool, min(n, len(pool)))
        used.update(d["source_id"] for d in chosen)
        return chosen

    def record(kind: str, device: dict, detail: str, duplicate_of: str = "") -> None:
        entry = {"type": kind, "source_id": device["source_id"], "name": device["name"], "detail": detail}
        if duplicate_of:
            entry["duplicate_of"] = duplicate_of
        issues.append(entry)

    # 1. Ausgetretene Benutzer, deren Geräte noch in Betrieb sind
    laptops_in_use = [d for d in devices if d["category"] == "laptop" and d["install_status"] in IN_USE]
    leavers: list[str] = []
    for d in pick(laptops_in_use, k("assigned_to_inactive_user")):
        if d["assigned_to"] not in leavers:
            leavers.append(d["assigned_to"])
    for user_name in leavers:
        users_by_name[user_name]["active"] = "false"
        for d in devices:
            if d["assigned_to"] == user_name and d["install_status"] in IN_USE:
                used.add(d["source_id"])
                record("assigned_to_inactive_user", d, f"Benutzer {user_name} ist inaktiv")

    # 2. Endgeräte in Betrieb ohne Benutzer
    endpoints_installed = [d for d in devices if d["category"] in ENDPOINTS and d["install_status"] == INSTALLED]
    for d in pick(endpoints_installed, k("installed_without_user")):
        record("installed_without_user", d, f"Benutzer {d['assigned_to']} entfernt")
        d["assigned_to"] = ""

    # 3. Ausgemusterte Endgeräte, die noch einem Benutzer zugewiesen sind
    active_users = [u for u in users if u["active"] == "true"]
    retired_endpoints = [d for d in devices if d["category"] in ENDPOINTS and d["install_status"] == RETIRED]
    for d in pick(retired_endpoints, k("retired_with_user")):
        d["assigned_to"] = rng.choice(active_users)["user_name"]
        record("retired_with_user", d, f"noch zugewiesen an {d['assigned_to']}")

    # 4. Fehlende Seriennummer
    for d in pick(devices, k("missing_serial_number")):
        record("missing_serial_number", d, f"Seriennummer {d['serial_number']} entfernt")
        d["serial_number"] = ""

    # 5. Fehlender Standort
    for d in pick(devices, k("missing_location")):
        record("missing_location", d, f"Standort {d['location']} entfernt")
        d["location"] = ""

    # 6. Herstellername in abweichender Schreibweise
    with_variants = [d for d in devices if d["manufacturer"] in MANUFACTURER_VARIANTS]
    for d in pick(with_variants, k("manufacturer_name_variant")):
        variant = rng.choice(MANUFACTURER_VARIANTS[d["manufacturer"]])
        record("manufacturer_name_variant", d, f"{variant} statt {d['manufacturer']}")
        d["manufacturer"] = variant

    # 7. Dubletten aus einer zweiten Quelle (Netzwerk-Scan)
    scannable = [
        d for d in devices
        if d["category"] in ("laptop", "desktop", "server") and d["install_status"] == INSTALLED
    ]
    n_same = k("duplicate_same_serial")
    n_variant = k("duplicate_serial_variant")
    n_name = k("duplicate_same_name_no_serial")
    originals = pick(scannable, n_same + n_variant + n_name)
    taken_macs = {d["mac_address"] for d in devices}
    duplicates: list[dict] = []
    for i, original in enumerate(originals, start=1):
        fqdn = f"{original['name'].lower()}.{DOMAIN}"
        serial = original["serial_number"]
        if i <= n_same:
            kind, row = "duplicate_same_serial", scan_copy(original, i, fqdn, serial)
            detail = "gleiche Seriennummer, Name als FQDN"
        elif i <= n_same + n_variant:
            if serial.lower() != serial and i % 2:
                variant, how = serial.lower(), "in Kleinbuchstaben"
            else:
                variant, how = f"{serial} ", "mit Leerzeichen am Ende"
            kind, row = "duplicate_serial_variant", scan_copy(original, i, fqdn, variant)
            # Der Scan sieht eine zweite Netzwerkkarte (z. B. WLAN): andere MAC, keine IP.
            # So kann die IRE nicht über MAC oder IP (Regeln 500 bis 800) zuordnen,
            # nur noch über die Seriennummer.
            row["mac_address"] = new_mac(rng, taken_macs)
            row["ip_address"] = ""
            detail = f"Seriennummer {how}, Name als FQDN, andere MAC (zweite Netzwerkkarte), keine IP"
        else:
            kind, row = "duplicate_same_name_no_serial", scan_copy(original, i, original["name"], "")
            detail = "gleicher Name, keine Seriennummer"
        duplicates.append(row)
        record(kind, row, detail, duplicate_of=original["source_id"])

    return duplicates, issues


# ---------------------------------------------------------------- Software/SAM

def make_software() -> list[dict]:
    return [
        {
            "publisher": s.publisher,
            "product": s.product,
            "display_name": s.display_name,
            "versions": " | ".join(s.versions),
            "license_metric": s.license_metric,
            "platforms": " | ".join(s.platforms),
        }
        for s in SOFTWARE
    ]


def make_installations(rng: random.Random, devices: list[dict], ref: date) -> list[dict]:
    rows = []
    for d in devices:
        if d["source"] != SOURCE_INVENTORY or d["category"] not in COMPUTERS or d["install_status"] not in IN_USE:
            continue
        platform = "mac" if d["os"] == "macOS" else "win"
        probabilities = dict(SOFTWARE_RANDOM_EXTRAS)
        for source in (SOFTWARE_BASELINE, SOFTWARE_BY_DEPARTMENT.get(d["department"], {})):
            for product, p in source.items():
                probabilities[product] = max(p, probabilities.get(product, 0.0))
        purchase = date.fromisoformat(d["purchase_date"])
        for sw in SOFTWARE:
            if platform not in sw.platforms:
                continue
            if rng.random() < probabilities.get(sw.product, 0.0):
                rows.append({
                    "device_source_id": d["source_id"],
                    "installed_on": d["name"],
                    "publisher": sw.publisher,
                    "display_name": sw.display_name,
                    "version": rng.choice(sw.versions),
                    "install_date": random_date(rng, purchase, ref).isoformat(),
                })
    return rows


def license_usage(installations: list[dict], devices: list[dict]) -> dict[str, int]:
    """Nutzung je lizenzpflichtigem Produkt, vereinfacht gezählt:
    Per Device = Anzahl Geräte mit Installation.
    Per User = Anzahl verschiedener Benutzer; Geräte ohne Benutzer zählen je einmal."""
    software_by_display = {s.display_name: s for s in SOFTWARE}
    device_by_id = {d["source_id"]: d for d in devices}
    device_ids: dict[str, list[str]] = defaultdict(list)
    for inst in installations:
        product = software_by_display[inst["display_name"]].product
        if inst["device_source_id"] not in device_ids[product]:
            device_ids[product].append(inst["device_source_id"])

    usage = {}
    for sw in SOFTWARE:
        if sw.license_metric == "Free":
            continue
        ids = device_ids.get(sw.product, [])
        if sw.license_metric == "Per Device":
            usage[sw.product] = len(ids)
        else:
            assigned = [device_by_id[i]["assigned_to"] for i in ids]
            usage[sw.product] = len({u for u in assigned if u}) + sum(1 for u in assigned if not u)
    return usage


def make_entitlements(usage: dict[str, int], ref: date) -> list[dict]:
    rows = []
    software_by_product = {s.product: s for s in SOFTWARE}
    for i, (product, (delta, unit_cost, subscription)) in enumerate(LICENSE_PLAN.items(), start=1):
        sw = software_by_product[product]
        if subscription:
            start, end = date(ref.year, 1, 1).isoformat(), date(ref.year, 12, 31).isoformat()
        else:
            start, end = date(ref.year - 3, 3, 1).isoformat(), ""
        rows.append({
            "license_id": f"LIC-{i:04d}",
            "publisher": sw.publisher,
            "product": product,
            "metric": sw.license_metric,
            "purchased_rights": max(1, usage[product] + delta),
            "unit_cost": unit_cost,
            "start_date": start,
            "end_date": end,
        })
    return rows


def sam_expectation(usage: dict[str, int], entitlements: list[dict]) -> list[dict]:
    rights = {e["product"]: e["purchased_rights"] for e in entitlements}
    software_by_product = {s.product: s for s in SOFTWARE}
    rows = []
    for product, used in usage.items():
        purchased = rights.get(product, 0)
        diff = purchased - used
        if product not in rights:
            status = "ohne Lizenz"
        elif used == 0:
            status = "ungenutzt"  # Lizenz gekauft, aber nirgends installiert (Shelfware)
        elif diff < 0:
            status = "unterlizenziert"
        elif diff > 0:
            status = "überlizenziert"
        else:
            status = "ausgeglichen"
        rows.append({
            "product": product,
            "publisher": software_by_product[product].publisher,
            "metric": software_by_product[product].license_metric,
            "purchased_rights": purchased,
            "usage": used,
            "difference": diff,
            "status": status,
        })
    return rows


# ------------------------------------------------------------------ Gesamtlauf

def generate(seed: int = DEFAULT_SEED, count: int = DEFAULT_COUNT, ref: date = DEFAULT_REFERENCE_DATE) -> dict:
    if count < MIN_COUNT:
        raise ValueError(f"count muss mindestens {MIN_COUNT} sein")
    rng = random.Random(seed)

    users = make_users(rng, round(count * 0.65))
    base_devices = make_devices(rng, count, ref, users)
    duplicates, issues = inject_issues(rng, base_devices, users)
    devices = base_devices + duplicates
    installations = make_installations(rng, devices, ref)
    usage = license_usage(installations, devices)
    entitlements = make_entitlements(usage, ref)

    in_use = [d for d in base_devices if d["install_status"] in IN_USE]
    ground_truth = {
        "parameters": {"seed": seed, "count": count, "reference_date": ref.isoformat()},
        "notes": [
            "Kennzahlen beziehen sich auf die Geräte aus dem Inventar-Export (ohne Scan-Dubletten).",
            "In Betrieb = install_status Installed oder In Maintenance.",
            "Lizenznutzung ist vereinfacht gezählt (siehe license_usage im Generator).",
        ],
        "counts": {
            "devices_inventory": len(base_devices),
            "devices_scan_duplicates": len(duplicates),
            "device_rows_total": len(devices),
            "users": len(users),
            "users_inactive": sum(1 for u in users if u["active"] == "false"),
            "installations": len(installations),
            "by_category": dict(Counter(d["category"] for d in base_devices)),
            "by_status": dict(Counter(d["install_status"] for d in base_devices)),
        },
        "kpis": {
            "warranty_ends_2027_all": sum(d["warranty_expiration"].startswith("2027") for d in base_devices),
            "warranty_ends_2027_in_use": sum(d["warranty_expiration"].startswith("2027") for d in in_use),
            "warranty_expired_in_use": sum(d["warranty_expiration"] < ref.isoformat() for d in in_use),
            "windows10_in_use": sum(d["os"].startswith("Windows 10") for d in in_use),
        },
        "issue_types": ISSUE_TYPES,
        "issue_counts": dict(Counter(i["type"] for i in issues)),
        "issues": issues,
        "sam": sam_expectation(usage, entitlements),
    }

    return {
        "locations": make_locations(),
        "departments": make_departments(),
        "users": users,
        "models": make_models(),
        "devices": devices,
        "software": make_software(),
        "installations": installations,
        "entitlements": entitlements,
        "ground_truth": ground_truth,
    }


def write_output(data: dict, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for table in TABLES:
        rows = data[table]
        with (out / f"{table}.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    (out / "ground_truth.json").write_text(
        json.dumps(data["ground_truth"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def print_summary(data: dict, out: Path) -> None:
    gt = data["ground_truth"]
    c = gt["counts"]
    print(f"Testdaten geschrieben nach {out}")
    print(f"  Geräte: {c['devices_inventory']} aus dem Inventar + {c['devices_scan_duplicates']} Scan-Dubletten"
          f" = {c['device_rows_total']} Zeilen")
    print(f"  Benutzer: {c['users']} (davon inaktiv: {c['users_inactive']}), Installationen: {c['installations']}")
    print("  Eingebaute Fehler:")
    for kind, n in gt["issue_counts"].items():
        print(f"    {n:3d}  {ISSUE_TYPES[kind]}")
    k = gt["kpis"]
    print(f"  Garantieende 2027 (in Betrieb): {k['warranty_ends_2027_in_use']}, "
          f"Garantie abgelaufen (in Betrieb): {k['warranty_expired_in_use']}, "
          f"Windows 10 (in Betrieb): {k['windows10_in_use']}")
    print("  Lizenzen:")
    for row in gt["sam"]:
        print(f"    {row['product']:<36} Rechte {row['purchased_rights']:3d}  Nutzung {row['usage']:3d}  {row['status']}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Erzeugt erfundene ITAM-Testdaten für die ServiceNow-Demo.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help=f"Zufalls-Seed (Standard {DEFAULT_SEED})")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT,
                        help=f"Anzahl Geräte ohne Dubletten (Standard {DEFAULT_COUNT}, mindestens {MIN_COUNT})")
    parser.add_argument("--reference-date", type=date.fromisoformat, default=DEFAULT_REFERENCE_DATE,
                        help=f"Stichtag JJJJ-MM-TT (Standard {DEFAULT_REFERENCE_DATE.isoformat()})")
    parser.add_argument("--out", type=Path, default=OUTPUT_DIR, help="Ausgabeordner")
    args = parser.parse_args(argv)
    if args.count < MIN_COUNT:
        parser.error(f"--count muss mindestens {MIN_COUNT} sein")

    data = generate(args.seed, args.count, args.reference_date)
    write_output(data, args.out)
    print_summary(data, args.out)


if __name__ == "__main__":
    main()
