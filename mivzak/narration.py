"""Template-style Hebrew sentences built from verified market data.

Every sentence here mirrors the wording of the IBI template ("המסחר בוול
סטריט ננעל אמש במגמה חיובית", "בגזרת הסחורות, מחיר חבית נפט מסוג WTI עלה
אמש ב...").  Numbers are spelled out for narration and verbs rotate so that
consecutive days do not read identically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from .hebrew_numbers import (
    basis_points_phrase,
    dollars_phrase,
    percent_phrase,
    yield_phrase,
)
from .market_data import MarketSnapshot, Quote

FLAT_THRESHOLD = 0.05
BIG_MOVE = 2.0
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
    ("up", "small", "m"): ["עלה ב{p}", "הוסיף {p0} לערכו", "התחזק ב{p}", "טיפס ב{p}", "רשם עלייה של {p0}"],
    ("up", "small", "f"): ["עלתה ב{p}", "הוסיפה {p0} לערכה", "התחזקה ב{p}", "טיפסה ב{p}", "רשמה עלייה של {p0}"],
    ("up", "big", "m"): ["זינק ב{p}", "קפץ ב{p}", "טיפס ב{p}"],
    ("up", "big", "f"): ["זינקה ב{p}", "קפצה ב{p}", "טיפסה ב{p}"],
    ("down", "small", "m"): ["ירד ב{p}", "איבד {p0} מערכו", "נחלש ב{p}", "השיל {p0} מערכו", "רשם ירידה של {p0}"],
    ("down", "small", "f"): ["ירדה ב{p}", "איבדה {p0} מערכה", "נחלשה ב{p}", "השילה {p0} מערכה", "רשמה ירידה של {p0}"],
    ("down", "big", "m"): ["צנח ב{p}", "נפל ב{p}", "ירד בחדות ב{p}"],
    ("down", "big", "f"): ["צנחה ב{p}", "נפלה ב{p}", "ירדה בחדות ב{p}"],
}
_FLAT = {"m": "סיים את היום כמעט ללא שינוי", "f": "סיימה את היום כמעט ללא שינוי"}


@dataclass
class Paragraph:
    category: str
    text: str
    origin: str = "data"
    sources: list = field(default_factory=list)
    source_ids: list = field(default_factory=list)

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
        if adverb:
            verb, rest = clause.split(" ", 1)
            clause = f"{verb} {adverb} {rest}"
        return clause
    direction = "up" if pct > 0 else "down"
    size = "big" if abs(pct) >= BIG_MOVE else "small"
    pattern = styler.pick(_VERBS[(direction, size, gender)])
    clause = pattern.format(p=phrase, p0=phrase)
    if adverb:
        verb, rest = clause.split(" ", 1)
        clause = f"{verb} {adverb} {rest}"
    return clause


def join_clauses(clauses: list, long: bool = False) -> str:
    clauses = [clause for clause in clauses if clause]
    if not clauses:
        return ""
    if len(clauses) == 1:
        return clauses[0]
    separator = ", ו" if long else " ו"
    return ", ".join(clauses[:-1]) + separator + clauses[-1]


def _quote_source(quote: Quote) -> dict:
    return {"label": quote.provider, "url": quote.url, "title": quote.label}


def us_close_paragraph(snapshot: MarketSnapshot, styler: Styler) -> Paragraph | None:
    if snapshot.us_market_closed:
        return Paragraph(
            "us_close",
            "המסחר בוול סטריט לא התקיים אמש, בשל יום חג בארצות הברית.",
            sources=[{"label": "Yahoo Finance", "url": "https://finance.yahoo.com/quote/%5EGSPC/", "title": "S&P 500"}],
        )
    quotes = [snapshot.quote(symbol) for symbol in ("^GSPC", "^IXIC", "^DJI")]
    quotes = [quote for quote in quotes if quote]
    if not quotes:
        return None
    trend = trend_word([quote.change_percent for quote in quotes])
    if trend == "ללא שינוי":
        first = "המסחר בוול סטריט ננעל אמש ללא שינוי מהותי במדדים המובילים."
    else:
        first = f"המסחר בוול סטריט ננעל אמש במגמה {trend}."
    clauses = [f"{quote.label} {move_clause(quote.change_percent, 'm', styler)}" for quote in quotes]
    second = join_clauses(clauses) + "."
    return Paragraph("us_close", f"{first} {second}", sources=[_quote_source(q) for q in quotes])


def sectors_paragraph(snapshot: MarketSnapshot, styler: Styler) -> Paragraph | None:
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
    elif best_up and not worst_down:
        tail = (
            f"וסקטור {worst.sector_name} עלה בשיעור המתון ביותר, של {percent_phrase(worst.change_percent, '')}"
            if worst.change_percent > FLAT_THRESHOLD
            else f"וסקטור {worst.sector_name} סיים כמעט ללא שינוי"
        )
        text = (
            f"בגזרת הסקטורים, העליות היו רוחביות: סקטור {best.sector_name} הוביל עם עלייה של "
            f"{percent_phrase(best.change_percent, '')}, {tail}."
        )
    elif worst_down and not best_up:
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


def rates_paragraph(snapshot: MarketSnapshot, styler: Styler) -> Paragraph | None:
    quote = snapshot.quote("^TNX")
    if quote is None:
        return None
    level = yield_phrase(quote.price)
    change = basis_points_phrase(quote.basis_points)
    if change is None:
        text = f'באפיק האג"ח, {quote.label} נותרה אמש כמעט ללא שינוי, ברמה של {level}.'
    else:
        verb = "עלתה" if quote.basis_points > 0 else "ירדה"
        text = f'באפיק האג"ח, {quote.label} {verb} אמש ב{change} ונקבעה על {level}.'
    return Paragraph("rates", text, sources=[_quote_source(quote)])


def commodities_paragraph(snapshot: MarketSnapshot, styler: Styler) -> Paragraph | None:
    oil = snapshot.quote("CL=F")
    gold = snapshot.quote("GC=F")
    clauses = []
    if oil:
        price = dollars_phrase(oil.price)
        if percent_phrase(oil.change_percent) is None:
            clauses.append(f"מחיר חבית נפט מסוג WTI נותר אמש כמעט ללא שינוי, סביב {price} לחבית")
        else:
            clauses.append(
                f"מחיר חבית נפט מסוג WTI {move_clause(oil.change_percent, 'm', styler, adverb='אמש')} "
                f"ונקבע על מחיר של {price} לחבית"
            )
    if gold:
        price = dollars_phrase(gold.price, step=10, approximate=True)
        if percent_phrase(gold.change_percent) is None:
            clauses.append(f"מחיר אונקיית הזהב נותר כמעט ללא שינוי, סביב {price} לאונקיה")
        else:
            clauses.append(
                f"מחיר אונקיית הזהב {move_clause(gold.change_percent, 'm', styler)} "
                f"ונקבע על מחיר של {price} לאונקיה"
            )
    if not clauses:
        return None
    text = "בגזרת הסחורות, " + join_clauses(clauses, long=True) + "."
    return Paragraph("commodities", text, sources=[_quote_source(q) for q in (oil, gold) if q])


def leader_paragraph(snapshot: MarketSnapshot, styler: Styler) -> Paragraph | None:
    leader = snapshot.leader
    if leader is None:
        return None
    templates = [
        "בזירת המניות, מניית {name} בלטה אמש בראש רשימת המניות העולות של Yahoo Finance, עם זינוק של {p0}.",
        "בזירת המניות, מניית {name} הובילה אמש את רשימת המניות העולות של Yahoo Finance, לאחר שזינקה ב{p}.",
        "בזירת המניות, בראש רשימת המניות העולות של Yahoo Finance בלטה אמש מניית {name}, שקפצה ב{p}.",
    ]
    text = styler.pick(templates).format(
        name=leader.name,
        p=percent_phrase(leader.change_percent, ""),
        p0=percent_phrase(leader.change_percent, ""),
    )
    sources = [{"label": "Yahoo Finance", "url": "https://finance.yahoo.com/markets/stocks/gainers/", "title": "Top gainers"}]
    loser = snapshot.biggest_loser
    if loser and loser.change_percent <= -EXTREME_LOSER:
        text += (
            f" מנגד, מניית {loser.name} בלטה לשלילה עם צניחה של "
            f"{percent_phrase(loser.change_percent, '')}."
        )
        sources.append({"label": "Yahoo Finance", "url": "https://finance.yahoo.com/markets/stocks/losers/", "title": "Top losers"})
    return Paragraph("leader", text, sources=sources)


def europe_paragraph(snapshot: MarketSnapshot, styler: Styler) -> Paragraph | None:
    quotes = [snapshot.quote(symbol) for symbol in ("^GDAXI", "^FTSE", "^STOXX50E")]
    quotes = [quote for quote in quotes if quote]
    if not quotes:
        return None
    trend = trend_word([quote.change_percent for quote in quotes])
    first = {
        "חיובית": "באירופה, המסחר ננעל אמש בעליות שערים.",
        "שלילית": "באירופה, המסחר ננעל אמש בירידות שערים.",
        "מעורבת": "באירופה, המסחר ננעל אמש במגמה מעורבת.",
        "ללא שינוי": "באירופה, המסחר ננעל אמש ללא שינוי מהותי.",
    }[trend]
    clauses = [f"{quote.label} {move_clause(quote.change_percent, 'm', styler)}" for quote in quotes]
    return Paragraph("europe_close", f"{first} {join_clauses(clauses)}.", sources=[_quote_source(q) for q in quotes])


def build_data_paragraphs(snapshot: MarketSnapshot, trading_date: date) -> list:
    styler = styler_for(trading_date)
    builders = [
        us_close_paragraph,
        sectors_paragraph,
        rates_paragraph,
        commodities_paragraph,
        leader_paragraph,
        europe_paragraph,
    ]
    paragraphs = []
    for builder in builders:
        paragraph = builder(snapshot, styler)
        if paragraph:
            paragraphs.append(paragraph)
    return paragraphs


def sentence_fingerprints(text: str) -> list:
    fingerprints = []
    for sentence in re.split(r"[.!?]+", text):
        fingerprint = re.sub(r"[^0-9A-Za-zא-ת]+", "", sentence).lower()
        if len(fingerprint) >= 18:
            fingerprints.append(fingerprint)
    return fingerprints


def order_paragraphs(paragraphs: list) -> list:
    rank = {category: index for index, category in enumerate(CATEGORY_ORDER)}
    return sorted(paragraphs, key=lambda paragraph: rank.get(paragraph.category, len(rank)))


def already_covered_text(paragraphs: list) -> str:
    return "\n".join(f"- {paragraph.text}" for paragraph in paragraphs)
