"""The committed "already sent" marker shared by the primary and backup runs."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path

from .config import ISRAEL_TZ, STATE_PATH


def load_state(path: Path = STATE_PATH) -> dict:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def already_sent(state: dict, trading_date: date, recipient: str) -> bool:
    return (
        state.get("trading_date") == trading_date.isoformat()
        and str(state.get("recipient", "")).lower() == recipient.lower()
    )


def report_digest(paragraph_texts: list) -> str:
    return hashlib.sha256("\n".join(paragraph_texts).encode("utf-8")).hexdigest()


def write_state(*, trading_date: date, brief_date: date, role: str, recipient: str,
                paragraph_texts: list, now: datetime, path: Path = STATE_PATH) -> dict:
    payload = {
        "trading_date": trading_date.isoformat(),
        "brief_date": brief_date.isoformat(),
        "sent_at": now.astimezone(ISRAEL_TZ).isoformat(),
        "workflow_role": role,
        "recipient": recipient.lower(),
        "report_sha256": report_digest(paragraph_texts),
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload
