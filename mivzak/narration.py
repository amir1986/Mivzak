"""Template-style Hebrew sentences built from verified market data.

Every sentence mirrors the wording of the real IBI briefs:

    המסחר בוול סטריט ננעל אמש במגמה חיובית.
    מדד ה-S&P 500 עלה במחצית האחוז ומדד הנאסד"ק הוסיף ארבע עשיריות האחוז לערכו.

    באפיק אג"ח חו"ל, התשואה על אג"ח מדינה ארה"ב לעשר שנים עלתה אמש בשלוש
    נקודות בסיס ונקבעה על ארבעה אחוזים ושבעים ושתיים מאיות.

    בגזרת הסחורות, מחיר חבית נפט מסוג WTI עלה אמש בשמונה עשיריות האחוז ונקבע
    על מחיר של תשעים ואחד דולרים לחבית.

    באירופה, המסחר ננעל אמש בירידות שערים.
    באסיה, המדדים המובילים ננעלו אמש במגמה דומה.

A paragraph is a block; newline characters inside its text separate the
lines of the block.  Numbers are spelled out for narration, verbs rotate so
consecutive days do not read identically, and a Friday session is described
with "בסוף השבוע" instead of "אמש".
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date

from .hebrew_numbers import (
    basis_points_phrase,
    dollars_phrase,
    percent_phrase,
    round_half_up,
    yield_phrase,
)
from .market_data import MarketSnapshot, Quote

FLAT_THRESHOLD = 0.05
BIG_MOVE = 2.0
BIG_YIELD_MOVE_BP = 8
EXTREME_LOSER = 8.0

# Category order inside the body of the brief.
CATEGORY_ORDER = [
    "us_close",
    "sectors",
    "macro",
    "central_banks",
    "rates",
    "commodities",
    "earnings",
    "leader",
    "movers",
    "europe_close",
]

_VERBS = {
    ("up", "small", "m"): ["עלה ב{p}", "הוסיף {p} לערכו", "טיפס ב{p}", "התחזק ב{p}"],
    ("up", "small", "f"): ["עלתה ב{p}", "הוסיפה {p} לערכה", "טיפסה ב{p}", "התחזקה ב{p}"],
    ("up", "big", "m"): ["זינק ב{p}", "קפץ ב{p}"],
    ("up", "big", "f"): ["זינקה ב{p}", "קפצה ב{p}"],
    ("down", "small", "m"): ["ירד ב{p}", "איבד {p} מערכו", "נחלש ב{p}", "השיל {p} מערכו"],
    ("down", "small", "f"): ["ירדה ב{p}", "איבדה {p} מערכה", "נחלשה ב{p}", "השילה {p} מערכה"],
    ("down", "big", "m"): ["צנח ב{p}", "נפל ב{p}"],
    ("down", "big", "f"): ["צנחה ב{p}", "נפלה ב{p}"],
}
_FLAT = {"m": "סיים את היום כמעט ללא שינוי", "f": "סיימה את היום כמעט ללא שינוי"}
_TREND_PHRASES = {
    "חיובית": ["בעליות שערים", "במגמה חיובית"],
    "שלילית": ["בירידות שערים", "במגמה שלילית"],
    "מעורבת": ["במגמה מעורבת"],
    "ללא שינוי": ["ללא שינוי מהותי"],
}


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


def include_sectors() -> bool:
    return _env_flag("MIVZAK_INCLUDE_SECTORS")


def rates_min_basis_points() -> float:
    return _env_float("MIVZAK_RATES_MIN_BP", 3)


def gold_min_move() -> float:
    return _env_float("MIVZAK_GOLD_MIN_MOVE", 0.5)


@dataclass
class Paragraph:
    category: str
    text: str
    origin: str = "data"
    sources: list = field(default_factory=list)
    source_ids: list = field(default_factory=list)
    data: dict = field(default_factory=dict)

    @property
    def lines(self) -> list:
        return [line.strip() for line in self.text.split("\n") if line.strip()]

    def as_dict(self) -> dict:
        return {
            "category": self.category,
            "text": self.text,
            "origin": self.origin,
            "sources": self.sources,
            "source_ids": self.source_ids,
        }


class Styler:
    """Rotates verb variants; seeded by the date so days differ."""

    def __init__(self, seed: int = 0):
        self.seed = seed
        self.calls = 0

    def pick(self, options: list) -> str:
        choice = options[(self.seed + self.calls) % len(options)]
        self.calls += 1
        return choice


def styler_for(trading_date: date) -> Styler:
    return Styler(seed=trading_date.toordinal())


def when_phrase(trading_date: date) -> str:
    """"אמש" on a weekday, "בסוף השבוע" when the session was a Friday."""
    return "בסוף השבוע" if trading_date.weekday() == 4 else "אמש"


def trend_word(changes: list) -> str:
    ups = [value for value in changes if value > FLAT_THRESHOLD]
    downs = [value for value in changes if value < -FLAT_THRESHOLD]
    if ups and not downs:
        return "חיובית"
    if downs and not ups:
        return "שלילית"
    if not ups and not downs:
        return "ללא שינוי"
    return "מעורבת"


def move_clause(pct: float, gender: str, styler: Styler, adverb: str = "") -> str:
    """"עלה במחצית האחוז", optionally with an adverb after the verb."""
    phrase = percent_phrase(pct, "")
    if phrase is None:
        clause = _FLAT[gender]
    else:
        direction = "up" if pct > 0 else "down"
        size = "big" if abs(pct) >= BIG_MOVE else "small"
        clause = styler.pick(_VERBS[(direction, size, gender)]).format(p=phrase)
    if adverb:
        verb, rest = clause.split(" ", 1)
        clause = f"{verb} {adverb} {rest}"
    return clause


def join_clauses(clauses: list) -> str:
    clauses = [clause for clause in clauses if clause]
    if not clauses:
        return ""
    if len(clauses) == 1:
        return clauses[0]
    return ", ".join(clauses[:-1]) + " ו" + clauses[-1]


def _quote_source(quote: Quote) -> dict:
    return {"label": quote.provider, "url": quote.url, "title": quote.label}


def us_close_paragraph(snapshot: MarketSnapshot, styler: Styler, when: str) -> Paragraph | None:
    if snapshot.us_market_closed:
        return Paragraph(
            "us_close",
            f"המסחר בוול סטריט לא התקיים {when}, בשל יום חג בארצות הברית.",
            sources=[{"label": "Yahoo Finance", "url": "https://finance.yahoo.com/quote/%5EGSPC/", "title": "S&P 500"}],
        )
    quotes = [snapshot.quote(symbol) for symbol in ("^GSPC", "^IXIC")]
    quotes = [quote for quote in quotes if quote]
    if not quotes:
        return None
    trend = trend_word([quote.change_percent for quote in quotes])
    if trend == "ללא שינוי":
        first = f"המסחר בוול סטריט ננעל {when} ללא שינוי מהותי."
    else:
        first = f"המסחר בוול סטריט ננעל {when} במגמה {trend}."
    clauses = [f"{quote.label} {move_clause(quote.change_percent, 'm', styler)}" for quote in quotes]
    second = join_clauses(clauses) + "."
    return Paragraph("us_close", f"{first}\n{second}", sources=[_quote_source(q) for q in quotes])


def sectors_paragraph(snapshot: MarketSnapshot, styler: Styler, when: str) -> Paragraph | None:
    sectors = snapshot.sectors()
    if len(sectors) < 8:
        return None
    best = max(sectors, key=lambda quote: quote.change_percent)
    worst = min(sectors, key=lambda quote: quote.change_percent)
    best_up = best.change_percent > FLAT_THRESHOLD
    worst_down = worst.change_percent < -FLAT_THRESHOLD
    if best_up and worst_down:
        text = (
            f"בגזרת הסקטורים, סקטור {best.sector_name} בלט לחיוב עם עלייה של "
            f"{percent_phrase(best.change_percent, '')}, בעוד סקטור {worst.sector_name} "
            f"{move_clause(worst.change_percent, 'm', styler)}."
        )
    elif best_up:
        tail = (
            f"וסקטור {worst.sector_name} עלה בשיעור המתון ביותר, של {percent_phrase(worst.change_percent, '')}"
            if worst.change_percent > FLAT_THRESHOLD
            else f"וסקטור {worst.sector_name} סיים כמעט ללא שינוי"
        )
        text = (
            f"בגזרת הסקטורים, העליות היו רוחביות: סקטור {best.sector_name} הוביל עם עלייה של "
            f"{percent_phrase(best.change_percent, '')}, {tail}."
        )
    elif worst_down:
        tail = (
            f"בעוד סקטור {best.sector_name} ירד בשיעור המתון ביותר, של {percent_phrase(best.change_percent, '')}"
            if best.change_percent < -FLAT_THRESHOLD
            else f"בעוד סקטור {best.sector_name} סיים כמעט ללא שינוי"
        )
        text = (
            f"בגזרת הסקטורים, הירידות היו רוחביות: סקטור {worst.sector_name} בלט לשלילה עם ירידה של "
            f"{percent_phrase(worst.change_percent, '')}, {tail}."
        )
    else:
        text = "בגזרת הסקטורים, רוב הסקטורים סיימו את היום כמעט ללא שינוי."
    return Paragraph("sectors", text, sources=[_quote_source(best), _quote_source(worst)])


def rates_paragraph(snapshot: MarketSnapshot, styler: Styler, when: str) -> Paragraph | None:
    quote = snapshot.quote("^TNX")
    if quote is None:
        return None
    basis_points = quote.basis_points
    if abs(round_half_up(abs(basis_points))) < rates_min_basis_points():
        return None
    change = basis_points_phrase(basis_points)
    if change is None:
        return None
    level = yield_phrase(quote.price)
    label = 'התשואה על אג"ח מדינה ארה"ב לעשר שנים'
    if abs(basis_points) >= BIG_YIELD_MOVE_BP:
        capital = "הפסדי הון" if basis_points > 0 else "רווחי הון"
        verb = "זינקה" if basis_points > 0 else "צנחה"
        text = f'באפיק אג"ח חו"ל, נרשמו {capital}, כאשר {label} {verb} {when} ב{change} ונקבעה על {level}.'
    else:
        verb = "עלתה" if basis_points > 0 else "ירדה"
        text = f'באפיק אג"ח חו"ל, {label} {verb} {when} ב{change} ונקבעה על {level}.'
    return Paragraph("rates", text, sources=[_quote_source(quote)])


def commodities_paragraph(snapshot: MarketSnapshot, styler: Styler, when: str) -> Paragraph | None:
    oil = snapshot.quote("CL=F")
    gold = snapshot.quote("GC=F")
    if gold and abs(gold.change_percent) < gold_min_move():
        gold = None
    lines = []
    sources = []
    if oil:
        price = dollars_phrase(oil.price)
        if percent_phrase(oil.change_percent) is None:
            lines.append(f"בגזרת הסחורות, מחיר חבית נפט מסוג WTI נותר {when} כמעט ללא שינוי, סביב {price} לחבית.")
        else:
            lines.append(
                f"בגזרת הסחורות, מחיר חבית נפט מסוג WTI {move_clause(oil.change_percent, 'm', styler, adverb=when)} "
                f"ונקבע על מחיר של {price} לחבית."
            )
        sources.append(_quote_source(oil))
    if gold:
        price = dollars_phrase(gold.price, step=10, approximate=True)
        opening = "" if lines else "בגזרת הסחורות, "
        adverb = "" if lines else when
        lines.append(
            f"{opening}מחיר אונקיית הזהב {move_clause(gold.change_percent, 'm', styler, adverb=adverb)} "
            f"ונקבע על מחיר של {price} לאונקיה."
        )
        sources.append(_quote_source(gold))
    if not lines:
        return None
    return Paragraph("commodities", "\n".join(lines), sources=sources)


def leader_paragraph(snapshot: MarketSnapshot, styler: Styler, when: str) -> Paragraph | None:
    leader = snapshot.leader
    if leader is None:
        return None
    verb = "זינקה" if leader.change_percent >= BIG_MOVE else "עלתה"
    text = f"מניית {leader.name} {verb} {when} ב{percent_phrase(leader.change_percent, '')}."
    sources = [{"label": "Yahoo Finance", "url": "https://finance.yahoo.com/markets/stocks/gainers/", "title": "Top gainers"}]
    data = {"leader_name": leader.name}
    loser = snapshot.biggest_loser
    if loser and loser.change_percent <= -EXTREME_LOSER:
        text += f"\nמנגד, מניית {loser.name} צנחה {when} ב{percent_phrase(loser.change_percent, '')}."
        sources.append({"label": "Yahoo Finance", "url": "https://finance.yahoo.com/markets/stocks/losers/", "title": "Top losers"})
        data["loser_name"] = loser.name
    return Paragraph("leader", text, sources=sources, data=data)


def europe_paragraph(snapshot: MarketSnapshot, styler: Styler, when: str) -> Paragraph | None:
    europe = [snapshot.quote(symbol) for symbol in ("^GDAXI", "^FTSE", "^STOXX50E")]
    europe = [quote for quote in europe if quote]
    asia = [snapshot.quote(symbol) for symbol in ("^N225", "^HSI", "000001.SS")]
    asia = [quote for quote in asia if quote]
    if not europe and not asia:
        return None
    lines = []
    europe_trend = None
    if europe:
        europe_trend = trend_word([quote.change_percent for quote in europe])
        lines.append(f"באירופה, המסחר ננעל {when} {styler.pick(_TREND_PHRASES[europe_trend])}.")
    if asia:
        asia_trend = trend_word([quote.change_percent for quote in asia])
        if europe_trend == asia_trend and asia_trend in {"חיובית", "שלילית"}:
            lines.append(f"באסיה, המדדים המובילים ננעלו {when} במגמה דומה.")
        else:
            lines.append(f"באסיה, המדדים המובילים ננעלו {when} {_TREND_PHRASES[asia_trend][-1]}.")
    return Paragraph("europe_close", "\n".join(lines), sources=[_quote_source(q) for q in europe + asia])


def build_data_paragraphs(snapshot: MarketSnapshot, trading_date: date) -> list:
    styler = styler_for(trading_date)
    when = when_phrase(trading_date)
    builders = [us_close_paragraph]
    if include_sectors():
        builders.append(sectors_paragraph)
    builders.extend([rates_paragraph, commodities_paragraph, leader_paragraph, europe_paragraph])
    paragraphs = []
    for builder in builders:
        paragraph = builder(snapshot, styler, when)
        if paragraph:
            paragraphs.append(paragraph)
    return paragraphs


def sentence_fingerprints(text: str) -> list:
    fingerprints = []
    for sentence in re.split(r"[.!?\n]+", text):
        fingerprint = re.sub(r"[^0-9A-Za-zא-ת]+", "", sentence).lower()
        if len(fingerprint) >= 18:
            fingerprints.append(fingerprint)
    return fingerprints


def order_paragraphs(paragraphs: list) -> list:
    rank = {category: index for index, category in enumerate(CATEGORY_ORDER)}
    return sorted(paragraphs, key=lambda paragraph: rank.get(paragraph.category, len(rank)))


def already_covered_text(paragraphs: list) -> str:
    return "\n".join(f"- {line}" for paragraph in paragraphs for line in paragraph.lines)
