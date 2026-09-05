"""Constants shared by every Mivzak module."""

from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")
NEW_YORK_TZ = ZoneInfo("America/New_York")

DEFAULT_RECIPIENT = "hellybracha@gmail.com"

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = ROOT / "templates" / "mivzak_template.docx"
# The sent marker normally lives next to the code; a host repository that
# embeds this folder can point it elsewhere with MIVZAK_STATE_PATH.
STATE_PATH = Path(
    os.environ.get("MIVZAK_STATE_PATH", "").strip()
    or ROOT / ".github" / "state" / "mivzak-sent.json"
)
OUTPUT_DIR = ROOT / "generated"

# The three fixed sentences of the template.  They are never regenerated.
OPENING = "בוקר טוב לכל היועצות והיועצים והרי מבזק הידע של IBI על הבוקר."
PAUSE = "שניה הפסקה"
CLOSING = (
    "עד כאן מבזק הידע של IBI על הבוקר, תודה לכולם על ההאזנה "
    "ויום השקעות מוצלח."
)

HEBREW_WEEKDAYS = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]
HEBREW_MONTHS = {
    1: "בינואר",
    2: "בפברואר",
    3: "במרץ",
    4: "באפריל",
    5: "במאי",
    6: "ביוני",
    7: "ביולי",
    8: "באוגוסט",
    9: "בספטמבר",
    10: "באוקטובר",
    11: "בנובמבר",
    12: "בדצמבר",
}

# Sites the brief may quote, exactly as requested.
NEWS_DOMAINS = [
    "bizportal.co.il",
    "calcalist.co.il",
    "globes.co.il",
    "themarker.com",
    "marketwatch.com",
    "bloomberg.com",
]
MARKET_DATA_DOMAINS = [
    "finance.yahoo.com",
    "google.com",
    "sectorspdr.com",
    "cmegroup.com",
    "investing.com",
    "treasury.gov",
]
ALLOWED_DOMAINS = NEWS_DOMAINS + MARKET_DATA_DOMAINS
DOMAIN_LABELS = {
    "bizportal.co.il": "ביזפורטל",
    "calcalist.co.il": "כלכליסט",
    "globes.co.il": "גלובס",
    "themarker.com": "TheMarker",
    "marketwatch.com": "MarketWatch",
    "bloomberg.com": "Bloomberg",
    "finance.yahoo.com": "Yahoo Finance",
    "google.com": "Google Finance",
    "sectorspdr.com": "Sector SPDR",
    "cmegroup.com": "CME Group",
    "investing.com": "Investing.com",
    "treasury.gov": "משרד האוצר האמריקאי",
}


def recipient() -> str:
    value = os.environ.get("MIVZAK_RECIPIENT", "").strip()
    return value or DEFAULT_RECIPIENT


def hebrew_full_date(value) -> str:
    return (
        f"יום {HEBREW_WEEKDAYS[value.weekday()]}, "
        f"{value.day} {HEBREW_MONTHS[value.month]} {value.year}"
    )


def domain_label(domain: str) -> str:
    domain = domain.lower()
    for allowed, label in DOMAIN_LABELS.items():
        if domain == allowed or domain.endswith("." + allowed):
            return label
    return domain


def is_allowed_domain(domain: str) -> bool:
    domain = domain.lower()
    return any(
        domain == allowed or domain.endswith("." + allowed)
        for allowed in ALLOWED_DOMAINS
    )
