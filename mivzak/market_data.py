"""Verified market data for one trading day.

Yahoo Finance is the primary provider (one batched quote request after the
cookie/crumb handshake, then the per-symbol chart endpoint as a fallback).
The US Treasury daily yield curve backs up the ten-year yield.  Every value
carries the exchange timestamp so the narration only ever uses figures that
were stamped on the requested trading date.
"""

from __future__ import annotations

import html
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import date, datetime, time as datetime_time, timedelta
from zoneinfo import ZoneInfo

from .config import NEW_YORK_TZ
from .http import HttpError, RETRY_STATUSES, Session

YAHOO_LABEL = "Yahoo Finance"
TREASURY_LABEL = "משרד האוצר האמריקאי"

INSTRUMENTS = {
    "^GSPC": ("מדד ה-S&P 500", "us_index"),
    "^IXIC": ('מדד הנאסד"ק', "us_index"),
    "^DJI": ("מדד הדאו ג'ונס", "us_index"),
    "^GDAXI": ("מדד הדאקס בפרנקפורט", "europe_index"),
    "^FTSE": ("מדד הפוטסי בלונדון", "europe_index"),
    "^STOXX50E": ("מדד היורוסטוקס 50", "europe_index"),
    "CL=F": ("מחיר חבית נפט מסוג WTI", "oil"),
    "GC=F": ("מחיר אונקיית הזהב", "gold"),
    "^TNX": ('תשואת האג"ח של ממשלת ארה"ב לעשר שנים', "us_10y_yield"),
}
ESSENTIAL_SYMBOLS = list(INSTRUMENTS)

SECTOR_ETFS = {
    "XLK": "הטכנולוגיה",
    "XLE": "האנרגיה",
    "XLF": "הפיננסים",
    "XLV": "הבריאות",
    "XLY": "הצריכה המחזורית",
    "XLP": "הצריכה הבסיסית",
    "XLI": "התעשייה",
    "XLB": "חומרי הגלם",
    "XLU": "התשתיות",
    "XLRE": 'הנדל"ן',
    "XLC": "התקשורת",
}

ALL_SYMBOLS = ESSENTIAL_SYMBOLS + list(SECTOR_ETFS)

QUOTE_FIELDS = ",".join(
    [
        "symbol",
        "shortName",
        "longName",
        "regularMarketPrice",
        "regularMarketChange",
        "regularMarketChangePercent",
        "regularMarketPreviousClose",
        "regularMarketTime",
        "marketState",
        "exchangeTimezoneName",
        "quoteType",
    ]
)

_COMPANY_SUFFIX_RE = re.compile(
    r"(,?\s+(?:Inc\.?|Incorporated|Corp\.?|Corporation|Ltd\.?|Limited|PLC|plc|"
    r"Co\.?|Company|N\.V\.|S\.A\.|SA|AG|SE|LLC|L\.P\.|LP|Holdings?|Group|"
    r"Class [A-C]|Common Stock|Ordinary Shares|ADR|American Depositary Shares))+$",
    flags=re.IGNORECASE,
)


def clean_company_name(name: str) -> str:
    cleaned = html.unescape(str(name or "")).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    previous = None
    while previous != cleaned:
        previous = cleaned
        cleaned = _COMPANY_SUFFIX_RE.sub("", cleaned).rstrip(" ,.")
    return cleaned or str(name or "").strip()


def raw_number(value) -> float | None:
    if isinstance(value, dict):
        value = value.get("raw")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return number


@dataclass
class Quote:
    symbol: str
    label: str
    kind: str
    price: float
    previous_close: float
    change_percent: float
    market_time: datetime | None
    provider: str
    url: str
    verified: bool
    sector_name: str | None = None

    @property
    def change(self) -> float:
        return self.price - self.previous_close

    @property
    def basis_points(self) -> float:
        return (self.price - self.previous_close) * 100


@dataclass
class Mover:
    symbol: str
    name: str
    change_percent: float
    price: float
    verified: bool
    market_time: datetime | None = None

    @property
    def url(self) -> str:
        return f"https://finance.yahoo.com/quote/{urllib.parse.quote(self.symbol, safe='')}/"


@dataclass
class MarketSnapshot:
    trading_date: date
    quotes: dict = field(default_factory=dict)
    gainers: list = field(default_factory=list)
    losers: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    us_market_closed: bool = False
    providers: list = field(default_factory=list)

    def quote(self, symbol: str, verified_only: bool = True) -> Quote | None:
        quote = self.quotes.get(symbol)
        if quote is None:
            return None
        if verified_only and not quote.verified:
            return None
        return quote

    def by_kind(self, kind: str, verified_only: bool = True) -> list:
        return [
            quote
            for symbol, quote in self.quotes.items()
            if quote.kind == kind and (quote.verified or not verified_only)
        ]

    def sectors(self, verified_only: bool = True) -> list:
        return self.by_kind("sector", verified_only)

    @property
    def leader(self) -> Mover | None:
        verified = [mover for mover in self.gainers if mover.verified]
        if not verified:
            return None
        return max(verified, key=lambda mover: mover.change_percent)

    @property
    def biggest_loser(self) -> Mover | None:
        verified = [mover for mover in self.losers if mover.verified]
        if not verified:
            return None
        return min(verified, key=lambda mover: mover.change_percent)

    def verified_count(self) -> int:
        return sum(1 for quote in self.quotes.values() if quote.verified)


def _timestamp_to_datetime(value, timezone_name: str | None) -> datetime | None:
    seconds = raw_number(value)
    if seconds is None:
        return None
    try:
        zone = ZoneInfo(timezone_name) if timezone_name else NEW_YORK_TZ
    except Exception:
        zone = NEW_YORK_TZ
    return datetime.fromtimestamp(int(seconds), zone)


def _label_and_kind(symbol: str) -> tuple[str, str, str | None]:
    if symbol in INSTRUMENTS:
        label, kind = INSTRUMENTS[symbol]
        return label, kind, None
    if symbol in SECTOR_ETFS:
        sector_name = SECTOR_ETFS[symbol]
        return f"סקטור {sector_name} ({symbol})", "sector", sector_name
    return symbol, "other", None


class _UrllibTransport:
    name = "urllib"

    def __init__(self):
        self.session = Session(delays=(12, 30), rate_limit_delay=20)

    def get(self, url: str, timeout: float = 25, attempts: int = 3) -> str:
        return self.session.get_text(url, timeout=timeout, attempts=attempts)


class _BrowserTransport:
    """curl_cffi with a Chrome fingerprint; only built when the module exists."""

    name = "browser"

    def __init__(self):
        from curl_cffi import requests as browser_requests  # type: ignore

        self.session = browser_requests.Session(impersonate="chrome")

    def get(self, url: str, timeout: float = 25, attempts: int = 3) -> str:
        last_status = None
        for attempt in range(1, attempts + 1):
            response = self.session.get(
                url,
                timeout=timeout,
                headers={"Accept-Language": "en-US,en;q=0.9"},
            )
            if response.status_code == 200:
                return response.text
            last_status = response.status_code
            if response.status_code in RETRY_STATUSES and attempt < attempts:
                time.sleep(15 * attempt)
                continue
            raise HttpError(url, response.status_code, f"HTTP {response.status_code}")
        raise HttpError(url, last_status, "retries exhausted")


class YahooClient:
    """Cookie/crumb aware Yahoo Finance client with transport fallback."""

    CRUMB_URL = "https://query2.finance.yahoo.com/v1/test/getcrumb"
    COOKIE_URL = "https://fc.yahoo.com"
    QUOTE_URL = "https://query2.finance.yahoo.com/v7/finance/quote"
    CHART_URL = "https://query2.finance.yahoo.com/v8/finance/chart/"
    SCREENER_URL = (
        "https://query2.finance.yahoo.com/v1/finance/screener/predefined/saved"
    )
    GAINERS_PAGE = "https://finance.yahoo.com/markets/stocks/gainers/"
    LOSERS_PAGE = "https://finance.yahoo.com/markets/stocks/losers/"

    def __init__(self, transports=None):
        self.transport = None
        self.crumb = ""
        self._candidates = transports
        self._primed = False

    def _build_candidates(self):
        if self._candidates is not None:
            return list(self._candidates)
        candidates = []
        try:
            candidates.append(_BrowserTransport())
        except Exception as error:
            print(f"Browser transport unavailable: {error}")
        candidates.append(_UrllibTransport())
        return candidates

    def _prime_transport(self, transport) -> bool:
        try:
            transport.get(self.COOKIE_URL, timeout=15, attempts=1)
        except HttpError as error:
            if error.status not in {404, 403}:
                print(f"Yahoo cookie warm-up warning ({transport.name}): {error}")
        except Exception as error:
            print(f"Yahoo cookie warm-up warning ({transport.name}): {error}")
        try:
            crumb = transport.get(self.CRUMB_URL, timeout=15, attempts=3).strip()
        except Exception as error:
            print(f"Yahoo crumb failed ({transport.name}): {error}")
            return False
        if not crumb or "<" in crumb or len(crumb) > 40:
            print(f"Yahoo crumb looked invalid ({transport.name}): {crumb[:40]!r}")
            return False
        self.transport = transport
        self.crumb = crumb
        print(f"Yahoo session ready via {transport.name} transport")
        return True

    def ensure_session(self) -> bool:
        if self.transport is not None:
            return True
        if self._primed:
            return False
        self._primed = True
        for transport in self._build_candidates():
            if self._prime_transport(transport):
                return True
            time.sleep(2)
        return False

    def _get_json(self, url: str, timeout: float = 25, attempts: int = 3):
        import json

        text = self.transport.get(url, timeout=timeout, attempts=attempts)
        return json.loads(text)

    def quotes(self, symbols: list) -> dict:
        """Return raw quote dicts keyed by symbol (empty on failure)."""
        if not self.ensure_session():
            return {}
        results = {}
        for start in range(0, len(symbols), 25):
            chunk = symbols[start:start + 25]
            query = urllib.parse.urlencode(
                {
                    "symbols": ",".join(chunk),
                    "fields": QUOTE_FIELDS,
                    "formatted": "false",
                    "lang": "en-US",
                    "region": "US",
                    "crumb": self.crumb,
                }
            )
            try:
                payload = self._get_json(f"{self.QUOTE_URL}?{query}")
            except Exception as error:
                print(f"Yahoo batched quote failed: {error}")
                continue
            for item in (payload.get("quoteResponse") or {}).get("result") or []:
                symbol = str(item.get("symbol") or "").strip()
                if symbol:
                    results[symbol] = item
            time.sleep(1.5)
        return results

    def chart(self, symbol: str, trading_date: date) -> dict | None:
        """Daily bars fallback: {price, previous_close, market_time, tz}."""
        if not self.ensure_session():
            return None
        query = urllib.parse.urlencode(
            {
                "range": "10d",
                "interval": "1d",
                "includePrePost": "false",
                "crumb": self.crumb,
            }
        )
        url = f"{self.CHART_URL}{urllib.parse.quote(symbol, safe='')}?{query}"
        try:
            payload = self._get_json(url, attempts=2)
            result = ((payload.get("chart") or {}).get("result") or [])[0]
        except Exception as error:
            print(f"Yahoo chart failed for {symbol}: {error}")
            return None
        meta = result.get("meta") or {}
        timezone_name = meta.get("exchangeTimezoneName")
        timestamps = result.get("timestamp") or []
        closes = (((result.get("indicators") or {}).get("quote") or [{}])[0]).get("close") or []
        chosen = None
        for index, stamp in enumerate(timestamps):
            observed = _timestamp_to_datetime(stamp, timezone_name)
            if observed and observed.date() == trading_date and index < len(closes):
                if closes[index] is not None:
                    chosen = index
        if chosen is None:
            return None
        price = raw_number(closes[chosen])
        previous = None
        for index in range(chosen - 1, -1, -1):
            previous = raw_number(closes[index]) if index < len(closes) else None
            if previous:
                break
        if not previous:
            previous = raw_number(meta.get("chartPreviousClose"))
        if price is None or not previous:
            return None
        return {
            "price": price,
            "previous_close": previous,
            "market_time": _timestamp_to_datetime(timestamps[chosen], timezone_name),
            "timezone": timezone_name,
        }

    def screener(self, screener_id: str, count: int = 10) -> list:
        if not self.ensure_session():
            return []
        query = urllib.parse.urlencode(
            {
                "formatted": "false",
                "lang": "en-US",
                "region": "US",
                "scrIds": screener_id,
                "count": count,
                "start": 0,
                "crumb": self.crumb,
            }
        )
        try:
            payload = self._get_json(f"{self.SCREENER_URL}?{query}", attempts=2)
            result = ((payload.get("finance") or {}).get("result") or [])[0]
            return result.get("quotes") or []
        except Exception as error:
            print(f"Yahoo screener {screener_id} failed: {error}")
            return []

    def movers_page(self, url: str) -> list:
        """Parse the public gainers/losers HTML table as a last resort."""
        if self.transport is None:
            if not self.ensure_session():
                return []
        try:
            page = self.transport.get(url, timeout=30, attempts=2)
        except Exception as error:
            print(f"Yahoo movers page failed: {error}")
            return []
        return parse_movers_table(page)


_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", flags=re.S)
_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", flags=re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_SYMBOL_LINK_RE = re.compile(r'href="/quote/([A-Za-z0-9.\-=^]+)/?"')
_PERCENT_RE = re.compile(r"([+-]?\d+(?:\.\d+)?)%")
_PRICE_RE = re.compile(r"^\s*([\d,]+(?:\.\d+)?)")


def parse_movers_table(page: str) -> list:
    """Extract [{symbol, name, price, change_percent}] from a Yahoo table."""
    rows = []
    for row_html in _ROW_RE.findall(page):
        link = _SYMBOL_LINK_RE.search(row_html)
        if not link:
            continue
        cells = [
            html.unescape(_TAG_RE.sub(" ", cell)).strip()
            for cell in _CELL_RE.findall(row_html)
        ]
        cells = [re.sub(r"\s+", " ", cell) for cell in cells]
        if len(cells) < 4:
            continue
        symbol = link.group(1)
        name = cells[1] if len(cells) > 1 else symbol
        percent = None
        price = None
        for cell in cells[2:]:
            if price is None:
                price_match = _PRICE_RE.match(cell)
                if price_match:
                    price = float(price_match.group(1).replace(",", ""))
            match = _PERCENT_RE.search(cell)
            if match and percent is None:
                percent = float(match.group(1))
        if percent is None:
            continue
        rows.append(
            {
                "symbol": symbol,
                "name": name or symbol,
                "price": price,
                "change_percent": percent,
            }
        )
    return rows


def treasury_ten_year(trading_date: date, session: Session | None = None) -> Quote | None:
    """The official daily 10-year par yield, when already published."""
    session = session or Session(delays=(5,), rate_limit_delay=5)
    entries = {}
    months = {trading_date.strftime("%Y%m")}
    months.add((trading_date.replace(day=1) - timedelta(days=1)).strftime("%Y%m"))
    for month in sorted(months):
        url = (
            "https://home.treasury.gov/resource-center/data-chart-center/"
            "interest-rates/pages/xml?data=daily_treasury_yield_curve"
            f"&field_tdr_date_value_month={month}"
        )
        try:
            text = session.get_text(url, timeout=30, attempts=2)
        except Exception as error:
            print(f"Treasury feed failed for {month}: {error}")
            continue
        for entry in re.findall(r"<entry>(.*?)</entry>", text, flags=re.S):
            day = re.search(r"<d:NEW_DATE[^>]*>([^<]+)<", entry)
            ten = re.search(r"<d:BC_10YEAR[^>]*>([^<]+)<", entry)
            if not day or not ten:
                continue
            try:
                entries[date.fromisoformat(day.group(1)[:10])] = float(ten.group(1))
            except ValueError:
                continue
    if trading_date not in entries:
        return None
    earlier = [day for day in entries if day < trading_date]
    if not earlier:
        return None
    previous_day = max(earlier)
    price = entries[trading_date]
    previous = entries[previous_day]
    label, kind = INSTRUMENTS["^TNX"]
    return Quote(
        symbol="US10Y",
        label=label,
        kind=kind,
        price=price,
        previous_close=previous,
        change_percent=((price - previous) / previous * 100) if previous else 0.0,
        market_time=datetime.combine(trading_date, datetime_time(17, 0), tzinfo=NEW_YORK_TZ),
        provider=TREASURY_LABEL,
        url="https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve",
        verified=True,
    )


def quote_from_yahoo(symbol: str, item: dict, trading_date: date) -> Quote | None:
    price = raw_number(item.get("regularMarketPrice"))
    previous = raw_number(item.get("regularMarketPreviousClose"))
    if price is None or not previous:
        return None
    change_percent = raw_number(item.get("regularMarketChangePercent"))
    if change_percent is None:
        change_percent = (price - previous) / previous * 100
    market_time = _timestamp_to_datetime(
        item.get("regularMarketTime"), item.get("exchangeTimezoneName")
    )
    label, kind, sector_name = _label_and_kind(symbol)
    return Quote(
        symbol=symbol,
        label=label,
        kind=kind,
        price=price,
        previous_close=previous,
        change_percent=change_percent,
        market_time=market_time,
        provider=YAHOO_LABEL,
        url=f"https://finance.yahoo.com/quote/{urllib.parse.quote(symbol, safe='')}/",
        verified=bool(market_time and market_time.date() == trading_date),
        sector_name=sector_name,
    )


def quote_from_chart(symbol: str, bar: dict, trading_date: date) -> Quote:
    label, kind, sector_name = _label_and_kind(symbol)
    price = bar["price"]
    previous = bar["previous_close"]
    return Quote(
        symbol=symbol,
        label=label,
        kind=kind,
        price=price,
        previous_close=previous,
        change_percent=(price - previous) / previous * 100,
        market_time=bar.get("market_time"),
        provider=YAHOO_LABEL,
        url=f"https://finance.yahoo.com/quote/{urllib.parse.quote(symbol, safe='')}/history/",
        verified=bool(bar.get("market_time") and bar["market_time"].date() == trading_date),
        sector_name=sector_name,
    )


def movers_from_screener(rows: list, trading_date: date) -> list:
    movers = []
    for row in rows[:10]:
        symbol = str(row.get("symbol") or "").strip()
        percent = raw_number(row.get("regularMarketChangePercent"))
        price = raw_number(row.get("regularMarketPrice"))
        if not symbol or percent is None or price is None:
            continue
        market_time = _timestamp_to_datetime(
            row.get("regularMarketTime"), row.get("exchangeTimezoneName")
        )
        name = clean_company_name(row.get("longName") or row.get("shortName") or symbol)
        movers.append(
            Mover(
                symbol=symbol,
                name=name,
                change_percent=percent,
                price=price,
                verified=bool(market_time and market_time.date() == trading_date),
                market_time=market_time,
            )
        )
    return movers


def movers_from_page(rows: list, verified: bool) -> list:
    movers = []
    for row in rows[:10]:
        movers.append(
            Mover(
                symbol=row["symbol"],
                name=clean_company_name(row["name"]),
                change_percent=row["change_percent"],
                price=row.get("price") or 0.0,
                verified=verified,
            )
        )
    return movers


def collect_market_data(trading_date: date, now: datetime | None = None, client: YahooClient | None = None) -> MarketSnapshot:
    snapshot = MarketSnapshot(trading_date=trading_date)
    client = client or YahooClient()
    now = now or datetime.now(NEW_YORK_TZ)

    raw_quotes = client.quotes(ALL_SYMBOLS)
    if raw_quotes:
        snapshot.providers.append(YAHOO_LABEL)
    for symbol in ALL_SYMBOLS:
        item = raw_quotes.get(symbol)
        if not item:
            continue
        quote = quote_from_yahoo(symbol, item, trading_date)
        if quote:
            snapshot.quotes[symbol] = quote

    missing = [
        symbol
        for symbol in ESSENTIAL_SYMBOLS
        if symbol not in snapshot.quotes or not snapshot.quotes[symbol].verified
    ]
    if missing and client.ensure_session():
        print(f"Trying the Yahoo chart endpoint for: {', '.join(missing)}")
        for symbol in missing:
            bar = client.chart(symbol, trading_date)
            if bar:
                snapshot.quotes[symbol] = quote_from_chart(symbol, bar, trading_date)
            time.sleep(1.5)

    us_quote = snapshot.quotes.get("^GSPC")
    if us_quote and not us_quote.verified and us_quote.market_time:
        ny_now = now.astimezone(NEW_YORK_TZ)
        after_close = ny_now.date() > trading_date or (
            ny_now.date() == trading_date and ny_now.time() >= datetime_time(16, 10)
        )
        if trading_date.weekday() < 5 and us_quote.market_time.date() < trading_date and after_close:
            snapshot.us_market_closed = True
            snapshot.warnings.append(
                "לפי Yahoo Finance לא התקיים מסחר בארה\"ב ביום המסחר; המבזק מתייחס ליום חג."
            )

    tnx = snapshot.quotes.get("^TNX")
    if tnx is None or not tnx.verified:
        treasury = treasury_ten_year(trading_date)
        if treasury:
            snapshot.quotes["^TNX"] = treasury
            snapshot.providers.append(TREASURY_LABEL)
        else:
            snapshot.warnings.append("לא נמצאה תשואת אג\"ח לעשר שנים מאומתת ליום המסחר.")

    gainers = movers_from_screener(client.screener("day_gainers"), trading_date)
    losers = movers_from_screener(client.screener("day_losers"), trading_date)
    # The public gainers/losers pages are live views of the current session,
    # so they only describe the requested trading date when that date is today
    # in New York and the session already traded.
    page_is_current = (
        now.astimezone(NEW_YORK_TZ).date() == trading_date
        and bool(us_quote and us_quote.verified)
        and not snapshot.us_market_closed
    )
    if not any(mover.verified for mover in gainers) and page_is_current:
        gainers = movers_from_page(client.movers_page(client.GAINERS_PAGE), True)
    if not any(mover.verified for mover in losers) and page_is_current:
        losers = movers_from_page(client.movers_page(client.LOSERS_PAGE), True)
    snapshot.gainers = gainers
    snapshot.losers = losers
    if not snapshot.leader:
        snapshot.warnings.append("לא נמצאה רשימת מניות עולות של Yahoo Finance מאומתת ליום המסחר.")

    for symbol in ESSENTIAL_SYMBOLS:
        quote = snapshot.quotes.get(symbol)
        if quote is None:
            snapshot.warnings.append(f"אין נתונים עבור {symbol}.")
        elif not quote.verified and not snapshot.us_market_closed:
            snapshot.warnings.append(f"הנתון של {symbol} אינו מיום המסחר ולכן לא נכלל.")
    return snapshot


def fixture_snapshot(trading_date: date) -> MarketSnapshot:
    """A realistic offline snapshot for tests and dry runs."""

    def make(symbol, price, previous, hour=16, tz=NEW_YORK_TZ):
        label, kind, sector_name = _label_and_kind(symbol)
        return Quote(
            symbol=symbol,
            label=label,
            kind=kind,
            price=price,
            previous_close=previous,
            change_percent=(price - previous) / previous * 100,
            market_time=datetime.combine(trading_date, datetime_time(hour, 0), tzinfo=tz),
            provider=YAHOO_LABEL,
            url=f"https://finance.yahoo.com/quote/{urllib.parse.quote(symbol, safe='')}/",
            verified=True,
            sector_name=sector_name,
        )

    berlin = ZoneInfo("Europe/Berlin")
    london = ZoneInfo("Europe/London")
    snapshot = MarketSnapshot(trading_date=trading_date, providers=[YAHOO_LABEL])
    snapshot.quotes = {
        "^GSPC": make("^GSPC", 7747.71, 7711.30),
        "^IXIC": make("^IXIC", 26584.06, 26480.10),
        "^DJI": make("^DJI", 53686.11, 53525.40),
        "^GDAXI": make("^GDAXI", 26003.32, 26184.90, hour=17, tz=berlin),
        "^FTSE": make("^FTSE", 10831.52, 10874.00, hour=16, tz=london),
        "^STOXX50E": make("^STOXX50E", 6382.59, 6440.20, hour=17, tz=berlin),
        "CL=F": make("CL=F", 91.30, 90.58),
        "GC=F": make("GC=F", 4539.90, 4548.00),
        "^TNX": make("^TNX", 4.762, 4.790),
        "XLK": make("XLK", 185.97, 183.40),
        "XLE": make("XLE", 64.62, 65.20),
        "XLF": make("XLF", 58.56, 58.30),
        "XLV": make("XLV", 173.26, 172.90),
        "XLY": make("XLY", 116.46, 115.80),
        "XLP": make("XLP", 85.26, 85.30),
        "XLI": make("XLI", 174.56, 173.90),
        "XLB": make("XLB", 52.62, 52.50),
        "XLU": make("XLU", 43.03, 43.10),
        "XLRE": make("XLRE", 44.25, 44.15),
        "XLC": make("XLC", 113.38, 112.70),
    }
    stamp = datetime.combine(trading_date, datetime_time(16, 0), tzinfo=NEW_YORK_TZ)
    snapshot.gainers = [
        Mover("SNOW", "Snowflake", 23.1, 312.40, True, stamp),
        Mover("AEHR", "Aehr Test Systems", 10.66, 84.40, True, stamp),
        Mover("ALAB", "Astera Labs", 9.97, 311.03, True, stamp),
    ]
    snapshot.losers = [
        Mover("AVGO", "Broadcom", -7.2, 402.10, True, stamp),
        Mover("LULU", "Lululemon Athletica", -17.35, 100.64, True, stamp),
    ]
    return snapshot
