"""Hebrew number words for a narrated market brief.

The template reads numbers aloud ("במחצית האחוז", "שלושים ושמונה אלף
מועסקים", "תשעים ואחד דולרים לחבית"), so every figure the brief produces
goes through this module.  Grammatical gender follows the counted noun:
percent (אחוז), dollar and basis-point *values* are masculine, while tenths
(עשיריות), hundredths (מאיות), points (נקודות) and basis points (נקודות
בסיס) are feminine.
"""

from __future__ import annotations

import math
import re

MASCULINE_UNITS = [
    "אפס", "אחד", "שניים", "שלושה", "ארבעה", "חמישה", "שישה", "שבעה",
    "שמונה", "תשעה", "עשרה", "אחד עשר", "שנים עשר", "שלושה עשר",
    "ארבעה עשר", "חמישה עשר", "שישה עשר", "שבעה עשר", "שמונה עשר",
    "תשעה עשר",
]
FEMININE_UNITS = [
    "אפס", "אחת", "שתיים", "שלוש", "ארבע", "חמש", "שש", "שבע", "שמונה",
    "תשע", "עשר", "אחת עשרה", "שתים עשרה", "שלוש עשרה", "ארבע עשרה",
    "חמש עשרה", "שש עשרה", "שבע עשרה", "שמונה עשרה", "תשע עשרה",
]
TENS = {
    2: "עשרים", 3: "שלושים", 4: "ארבעים", 5: "חמישים", 6: "שישים",
    7: "שבעים", 8: "שמונים", 9: "תשעים",
}
HUNDREDS = {
    1: "מאה", 2: "מאתיים", 3: "שלוש מאות", 4: "ארבע מאות", 5: "חמש מאות",
    6: "שש מאות", 7: "שבע מאות", 8: "שמונה מאות", 9: "תשע מאות",
}
THOUSANDS_CONSTRUCT = {
    1: "אלף", 2: "אלפיים", 3: "שלושת אלפים", 4: "ארבעת אלפים",
    5: "חמשת אלפים", 6: "ששת אלפים", 7: "שבעת אלפים", 8: "שמונת אלפים",
    9: "תשעת אלפים", 10: "עשרת אלפים",
}
SCALE_VALUES = {
    "אלף": 1_000,
    "אלפים": 1_000,
    "מיליון": 1_000_000,
    "מיליארד": 1_000_000_000,
}


def round_half_up(value: float) -> int:
    """Round like a person would (2.5 -> 3), not like Python (2.5 -> 2)."""
    return int(math.floor(float(value) + 0.5))


def _join(parts: list[str]) -> str:
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return " ".join(parts[:-1]) + " ו" + parts[-1]


def _under_thousand(n: int, gender: str) -> list[str]:
    units = MASCULINE_UNITS if gender == "m" else FEMININE_UNITS
    parts: list[str] = []
    hundreds, rest = divmod(n, 100)
    if hundreds:
        parts.append(HUNDREDS[hundreds])
    if rest:
        if rest < 20:
            parts.append(units[rest])
        else:
            tens, ones = divmod(rest, 10)
            parts.append(TENS[tens])
            if ones:
                parts.append(units[ones])
    return parts


def _scale_words(count: int, word: str) -> str:
    if count == 1:
        return word
    if count == 2:
        return "שני " + word
    return cardinal(count, "m", noun_follows=True) + " " + word


def _thousands_words(count: int) -> str:
    if count in THOUSANDS_CONSTRUCT:
        return THOUSANDS_CONSTRUCT[count]
    if count < 20:
        return MASCULINE_UNITS[count] + " אלף"
    return cardinal(count, "m") + " אלף"


def cardinal(n: int, gender: str = "m", noun_follows: bool = False) -> str:
    """Spell an integer.  ``noun_follows`` selects the construct form of 2."""
    n = int(n)
    if n < 0:
        return "מינוס " + cardinal(-n, gender, noun_follows)
    if n == 0:
        return "אפס"
    if n == 2 and noun_follows:
        return "שני" if gender == "m" else "שתי"

    parts: list[str] = []
    billions, n = divmod(n, 1_000_000_000)
    millions, n = divmod(n, 1_000_000)
    thousands, n = divmod(n, 1_000)
    if billions:
        parts.append(_scale_words(billions, "מיליארד"))
    if millions:
        parts.append(_scale_words(millions, "מיליון"))
    if thousands:
        parts.append(_thousands_words(thousands))
    parts.extend(_under_thousand(n, gender))
    return _join(parts)


def percent_phrase(pct: float, prefix: str = "ב") -> str | None:
    """Template style: 0.5 -> "במחצית האחוז", 5.5 -> "בכחמישה וחצי אחוזים".

    Returns None for a move smaller than five hundredths of a percent, which
    the narration treats as "no change".
    """
    magnitude = abs(float(pct))
    tenths = round_half_up(magnitude * 10)
    if tenths == 0:
        return None

    if tenths < 10:
        if tenths == 1:
            core = "עשירית האחוז"
        elif tenths == 2:
            core = "שתי עשיריות האחוז"
        elif tenths == 5:
            core = "מחצית האחוז"
        else:
            core = f"{FEMININE_UNITS[tenths]} עשיריות האחוז"
        return prefix + core

    if magnitude < 9.75:
        halves = round_half_up(magnitude * 2)
        whole, half = divmod(halves, 2)
        if whole == 1:
            core = "כאחוז וחצי" if half else "כאחוז"
        elif half:
            core = f"כ{MASCULINE_UNITS[whole]} וחצי אחוזים"
        else:
            core = f"כ{cardinal(whole, 'm', noun_follows=True)} אחוזים"
    else:
        whole = round_half_up(magnitude)
        core = f"כ{cardinal(whole, 'm', noun_follows=True)} אחוזים"
    return prefix + core


def basis_points_phrase(basis_points: float) -> str | None:
    count = abs(round_half_up(basis_points))
    if count == 0:
        return None
    if count == 1:
        return "נקודת בסיס אחת"
    if count == 2:
        return "שתי נקודות בסיס"
    return f"{cardinal(count, 'f')} נקודות בסיס"


def yield_phrase(value: float) -> str:
    """A yield level: 4.77 -> "ארבעה אחוזים ושבעים ושבע מאיות"."""
    value = float(value)
    whole = int(value)
    hundredths = round_half_up((value - whole) * 100)
    if hundredths >= 100:
        whole += 1
        hundredths -= 100

    if whole == 0:
        base = None
    elif whole == 1:
        base = "אחוז אחד" if hundredths == 0 else "אחוז"
    else:
        base = f"{cardinal(whole, 'm', noun_follows=True)} אחוזים"

    if hundredths == 0:
        fraction = None
    elif hundredths == 50:
        fraction = "חצי"
    elif hundredths == 25:
        fraction = "רבע"
    elif hundredths == 75:
        fraction = "שלושה רבעים"
    elif hundredths % 10 == 0:
        tenths = hundredths // 10
        if tenths == 1:
            fraction = "עשירית"
        elif tenths == 2:
            fraction = "שתי עשיריות"
        else:
            fraction = f"{FEMININE_UNITS[tenths]} עשיריות"
    elif hundredths == 1:
        fraction = "מאית אחת"
    else:
        fraction = f"{cardinal(hundredths, 'f')} מאיות"

    if base and fraction:
        return f"{base} ו{fraction}"
    if base:
        return base
    return f"{fraction} האחוז"


def dollars_phrase(amount: float, step: float = 1.0, approximate: bool = False) -> str:
    """91.3 -> "תשעים ואחד דולרים"; 4481 with step=10 -> "ארבעת אלפים ...".

    ``approximate`` prefixes the Hebrew "about" (כ) for coarsely rounded
    values.
    """
    units = round_half_up(float(amount) / step) * step
    count = int(round(units))
    if count == 1:
        phrase = "דולר אחד"
    elif count == 2:
        phrase = "שני דולרים"
    else:
        phrase = f"{cardinal(count, 'm', noun_follows=True)} דולרים"
    return ("כ" + phrase) if approximate else phrase


def count_phrase(n: int, singular: str, plural: str, gender: str = "m") -> str:
    n = int(n)
    if n == 1:
        return f"{singular} {'אחד' if gender == 'm' else 'אחת'}"
    if n == 2:
        return f"{'שני' if gender == 'm' else 'שתי'} {plural}"
    return f"{cardinal(n, gender, noun_follows=True)} {plural}"


def scaled_amount_phrase(value: float, scale_word: str) -> str:
    """"38 אלף" -> "שלושים ושמונה אלף"; "2.5 מיליארד" -> "שניים וחצי מיליארד"."""
    scale = SCALE_VALUES[scale_word]
    word = "אלף" if scale_word == "אלפים" else scale_word
    value = float(value)
    doubled = value * 2
    if value < 20 and abs(doubled - round(doubled)) < 1e-9 and int(round(doubled)) % 2 == 1:
        whole = int(value)
        if whole == 0:
            return f"חצי {word}"
        if whole == 1:
            return f"{word} וחצי"
        return f"{MASCULINE_UNITS[whole]} וחצי {word}"
    total = round_half_up(value * scale)
    return cardinal(total, "m")


_PREFIX = r"(?<![א-ת\d])(?P<prefix>בכ|לכ|מכ|[בלכמ])?-?\s?"
_NUMBER = r"(?P<num>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"
_PERCENT_RE = re.compile(_PREFIX + _NUMBER + r"\s?(?:%|אחוזים|אחוז)(?![א-ת])")
_BASIS_POINTS_RE = re.compile(_PREFIX + r"(?P<num>\d+)\s?נקודות בסיס")
_SCALED_RE = re.compile(
    _PREFIX + _NUMBER + r"\s?(?P<scale>אלפים|אלף|מיליון|מיליארד)(?![א-ת])"
)
_MONEY_RE = re.compile(
    _PREFIX + _NUMBER + r"\s?(?P<unit>דולרים|דולר|שקלים|שקל|ש\"ח|יורו|סנט)(?![א-ת])"
)
_POINTS_RE = re.compile(_PREFIX + _NUMBER + r"\s?נקודות(?![א-ת])")
_YEARS_RE = re.compile(_PREFIX + r"(?P<num>\d+)\s?שנים(?![א-ת])")
_COUNT_RE = re.compile(
    _PREFIX + _NUMBER
    + r"\s?(?P<noun>מועסקים|משרות|עובדים|מניות|חברות|סניפים|לקוחות)(?![א-ת])"
)
_COUNT_GENDER = {
    "מועסקים": ("מועסק", "m"),
    "משרות": ("משרה", "f"),
    "עובדים": ("עובד", "m"),
    "מניות": ("מניה", "f"),
    "חברות": ("חברה", "f"),
    "סניפים": ("סניף", "m"),
    "לקוחות": ("לקוח", "m"),
}


def _parse_number(raw: str) -> float:
    return float(raw.replace(",", ""))


def _replace_percent(match: re.Match) -> str:
    prefix = match.group("prefix") or ""
    value = _parse_number(match.group("num"))
    approximate = prefix.endswith("כ")
    head = prefix[:-1] if approximate else prefix
    if head in {"ל", "מ"}:
        return head + ("כ" if approximate else "") + yield_phrase(value)
    phrase = percent_phrase(value, "")
    if phrase is None:
        return match.group(0)
    if approximate and not phrase.startswith("כ"):
        phrase = "כ" + phrase
    return head + phrase


def _replace_basis_points(match: re.Match) -> str:
    phrase = basis_points_phrase(int(match.group("num")))
    return ((match.group("prefix") or "") + phrase) if phrase else match.group(0)


def _replace_scaled(match: re.Match) -> str:
    value = _parse_number(match.group("num"))
    return (match.group("prefix") or "") + scaled_amount_phrase(value, match.group("scale"))


def _replace_money(match: re.Match) -> str:
    value = _parse_number(match.group("num"))
    unit = match.group("unit")
    count = round_half_up(value)
    if count < 1:
        return match.group(0)
    if unit in {"דולר", "דולרים"}:
        words = dollars_phrase(count)
    elif unit in {"שקל", "שקלים"}:
        words = count_phrase(count, "שקל", "שקלים", "m")
    elif unit == "סנט":
        words = f"{cardinal(count, 'm', noun_follows=True)} סנט"
    else:
        words = f"{cardinal(count, 'm', noun_follows=True)} {unit}"
    return (match.group("prefix") or "") + words


def _replace_points(match: re.Match) -> str:
    value = round_half_up(_parse_number(match.group("num")))
    return (match.group("prefix") or "") + count_phrase(value, "נקודה", "נקודות", "f")


def _replace_years(match: re.Match) -> str:
    count = int(match.group("num"))
    if count == 1:
        words = "שנה"
    elif count == 2:
        words = "שנתיים"
    elif count <= 10:
        words = f"{cardinal(count, 'f')} שנים"
    else:
        words = f"{cardinal(count, 'f')} שנה"
    return (match.group("prefix") or "") + words


def _replace_count(match: re.Match) -> str:
    value = round_half_up(_parse_number(match.group("num")))
    noun = match.group("noun")
    singular, gender = _COUNT_GENDER[noun]
    return (match.group("prefix") or "") + count_phrase(value, singular, noun, gender)


def digits_to_words(text: str) -> str:
    """Rewrite the common numeric expressions of generated Hebrew in words."""
    text = _PERCENT_RE.sub(_replace_percent, text)
    text = _BASIS_POINTS_RE.sub(_replace_basis_points, text)
    text = _SCALED_RE.sub(_replace_scaled, text)
    text = _MONEY_RE.sub(_replace_money, text)
    text = _POINTS_RE.sub(_replace_points, text)
    text = _YEARS_RE.sub(_replace_years, text)
    text = _COUNT_RE.sub(_replace_count, text)
    return text


_ALLOWED_DIGIT_TOKENS = re.compile(
    r"(?:S&P\s?500|FTSE\s?100|Stoxx\s?50|STOXX\s?50|Nasdaq\s?100|Russell\s?2000"
    r"|TA-?(?:35|90|125)|ת\"א\s?(?:35|90|125)|תל אביב\s?(?:35|90|125)"
    r"|(?:19|20)\d\d)",
    flags=re.IGNORECASE,
)


def remaining_digit_tokens(text: str) -> list[str]:
    """Digit runs that survived ``digits_to_words`` and are not known names."""
    scrubbed = _ALLOWED_DIGIT_TOKENS.sub(" ", text)
    offenders = []
    for match in re.finditer(r"\d[\d.,:%]*", scrubbed):
        start = max(0, match.start() - 12)
        end = min(len(scrubbed), match.end() + 12)
        offenders.append(scrubbed[start:end].strip())
    return offenders
