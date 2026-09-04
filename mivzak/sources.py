"""Same-day news material from the requested sites.

Three layers, cheapest first:

1. RSS feeds of Globes, TheMarker, Yahoo Finance, MarketWatch and Bloomberg
   (no API key, always available).
2. Full article text for the most relevant Hebrew items and a few Yahoo
   items (Calcalist, Bizportal, MarketWatch and Bloomberg block scrapers, so
   their headlines and summaries come from the feeds or the search APIs).
3. Tavily and Exa web search restricted to the requested domains, when keys
   are configured.

Every item is kept only if it was published (or, for live blogs, updated)
on the requested trading date.
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from email.utils import parsedate_to_datetime

from .config import (
    ISRAEL_TZ,
    NEWS_DOMAINS,
    NEW_YORK_TZ,
    domain_label,
    is_allowed_domain,
)
from .http import HttpError, Session

FEEDS = [
    ("גלובס", "https://www.globes.co.il/webservice/rss/rssfeeder.asmx/FeederNode?iID=1225", "he", "markets"),
    ("גלובס", "https://www.globes.co.il/webservice/rss/rssfeeder.asmx/FeederNode?iID=585", "he", "markets"),
    ("גלובס", "https://www.globes.co.il/webservice/rss/rssfeeder.asmx/FeederNode?iID=2", "he", "general"),
    ("גלובס", "https://www.globes.co.il/webservice/rss/rssfeeder.asmx/FeederNode?iID=594", "he", "general"),
    ("TheMarker", "https://www.themarker.com/srv/tm-markets", "he", "markets"),
    ("TheMarker", "https://www.themarker.com/cmlink/1.145", "he", "general"),
    ("TheMarker", "https://www.themarker.com/srv/tm-news", "he", "general"),
    ("Yahoo Finance", "https://finance.yahoo.com/rss/topstories", "en", "general"),
    ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex", "en", "general"),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories", "en", "markets"),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines", "en", "markets"),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_marketpulse", "en", "markets"),
    ("Bloomberg", "https://feeds.bloomberg.com/markets/news.rss", "en", "markets"),
    ("Bloomberg", "https://feeds.bloomberg.com/economics/news.rss", "en", "general"),
]

KEYWORDS = {
    "וול סטריט": 3, "נאסד": 3, "s&p": 3, "דאו": 2, "מניית": 2, "מניה": 1, "מניות": 1,
    "זינק": 2, "צנח": 2, "נפל": 1, "קפצ": 1, "נפט": 2, "זהב": 2, "ריבית": 3, "הפד": 3,
    "פדרל": 2, "בנק ישראל": 3, "תשואות": 2, "תשואת": 2, 'אג"ח': 2, "דוחות": 2,
    'דו"ח': 1, "תוצאות": 1, "adp": 4, "תעסוקה": 2, "אמפייר": 4, "ecb": 3,
    "הבנק המרכזי": 2, "אירופה": 2, "דאקס": 2, "פוטסי": 2, "סטוקס": 2, "אינפלציה": 1,
    "מדד המחירים": 2, "משרות": 2, "בורסה": 1, "מסחר": 1, "ננעל": 2, "wall street": 3,
    "nasdaq": 3, "dow": 2, "stock": 1, "stocks": 2, "shares": 1, "earnings": 3,
    "results": 1, "fed ": 3, "fed's": 3, "federal reserve": 3, "rate decision": 3,
    "interest rate": 2, "treasury": 2, "yield": 2, "oil": 2, "crude": 2, "gold": 2,
    "empire state": 4, "manufacturing": 1, "jobs": 2, "payroll": 2, "surge": 2,
    "plunge": 2, "soar": 2, "tumble": 2, "jumps": 1, "falls": 1, "rally": 2,
    "selloff": 2, "sell-off": 2, "closes": 1, "record": 1, "bank of israel": 3,
    "european central bank": 3, "dax": 2, "ftse": 2, "stoxx": 2,
}

RSS_LIMIT_PER_FEED = 60
MAX_HEBREW_ARTICLES = 10
MAX_ENGLISH_ARTICLES = 4
MAX_SOURCES = 30
MAX_SOURCE_CHARS = 2600
MAX_TOTAL_CHARS = 60_000

_TAG_RE = re.compile(r"<[^>]+>")
_LD_JSON_RE = re.compile(
    r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', flags=re.S
)
_PARAGRAPH_RE = re.compile(r"<(?:p|h2|h3)[^>]*>(.*?)</(?:p|h2|h3)>", flags=re.S)
_META_DATE_RE = re.compile(
    r'(?:datePublished|dateModified|article:published_time|article:modified_time)'
    r'["\']?\s*(?:content=|[:=])\s*["\']([^"\']+)["\']'
)
_NOISE_MARKERS = (
    "{", "}", "window.", "function(", "©", "כל הזכויות שמורות", "cookie", "Skip to",
    "התחברות", "הרשמה", "newsletter", "Subscribe", "var ", "http",
)


def strip_html(value: str) -> str:
    text = html.unescape(_TAG_RE.sub(" ", str(value or "")))
    return re.sub(r"\s+", " ", text).strip()


def parse_datetime(raw) -> datetime | None:
    value = str(raw or "").strip()
    if not value:
        return None
    parsed = None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError, IndexError):
            parsed = None
    if parsed is None:
        match = re.match(r"(\d{4}-\d{2}-\d{2})", value)
        if match:
            try:
                parsed = datetime.fromisoformat(match.group(1))
            except ValueError:
                return None
        else:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ISRAEL_TZ)
    return parsed


def matches_trading_date(raw, trading_date: date) -> bool:
    parsed = parse_datetime(raw)
    if parsed is None:
        return False
    candidates = {
        parsed.astimezone(timezone.utc).date(),
        parsed.astimezone(ISRAEL_TZ).date(),
        parsed.astimezone(NEW_YORK_TZ).date(),
    }
    return trading_date in candidates


def relevance_score(text: str) -> int:
    lowered = (text or "").lower()
    return sum(weight for keyword, weight in KEYWORDS.items() if keyword in lowered)


def canonical_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), "", "")
    )


def normalized_domain(url: str) -> str:
    domain = urllib.parse.urlsplit(url).netloc.lower()
    return domain[4:] if domain.startswith("www.") else domain


def make_source(*, kind: str, label: str, title: str, url: str, published: str,
                content: str, lang: str, score: float, origin: str) -> dict:
    return {
        "kind": kind,
        "label": label,
        "title": strip_html(title)[:300],
        "url": url.strip(),
        "published": published,
        "content": content.strip()[:MAX_SOURCE_CHARS],
        "lang": lang,
        "score": float(score),
        "origin": origin,
        "verified_same_day": True,
    }


def parse_feed(xml_text: str) -> list:
    items = []
    try:
        root = ET.fromstring(xml_text.encode("utf-8"))
    except ET.ParseError:
        return items
    for node in root.iter("item"):
        def text_of(tag):
            element = node.find(tag)
            return (element.text or "").strip() if element is not None else ""
        pub = text_of("pubDate") or text_of("{http://purl.org/dc/elements/1.1/}date")
        link = text_of("link")
        if not link:
            link_element = node.find("{http://www.w3.org/2005/Atom}link")
            link = (link_element.get("href") if link_element is not None else "") or ""
        items.append(
            {
                "title": strip_html(text_of("title")),
                "link": link.split("#")[0].strip(),
                "description": strip_html(text_of("description")),
                "published": pub,
            }
        )
    return items


def collect_feed_items(trading_date: date, session: Session, feeds=None) -> list:
    """Same-day, relevant feed items across all feeds (deduplicated)."""
    seen = set()
    collected = []
    for label, url, lang, focus in feeds or FEEDS:
        try:
            xml_text = session.get_text(url, timeout=25, attempts=2)
        except Exception as error:
            print(f"Feed unavailable ({label}): {error}")
            continue
        items = parse_feed(xml_text)[:RSS_LIMIT_PER_FEED]
        accepted = 0
        for item in items:
            if not item["link"] or not item["title"]:
                continue
            if not is_allowed_domain(normalized_domain(item["link"])):
                continue
            if not matches_trading_date(item["published"], trading_date):
                continue
            key = canonical_url(item["link"])
            if key in seen:
                continue
            score = relevance_score(item["title"] + " " + item["description"])
            threshold = 1 if focus == "markets" else 3
            if score < threshold:
                continue
            seen.add(key)
            accepted += 1
            collected.append(
                {
                    **item,
                    "label": label,
                    "lang": lang,
                    "score": score + (1 if focus == "markets" else 0),
                }
            )
        print(f"Feed {label} ({focus}): {len(items)} items, {accepted} same-day and relevant")
        time.sleep(0.5)
    collected.sort(key=lambda item: -item["score"])
    return collected


def extract_article(page: str) -> dict:
    """Best-effort body text and dates from an article page."""
    body = ""
    published = ""
    modified = ""
    for block in _LD_JSON_RE.findall(page):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        candidates = data if isinstance(data, list) else [data]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            if "@graph" in candidate and isinstance(candidate["@graph"], list):
                candidates.extend(item for item in candidate["@graph"] if isinstance(item, dict))
            published = published or str(candidate.get("datePublished") or "")
            modified = modified or str(candidate.get("dateModified") or "")
            article_body = candidate.get("articleBody")
            if isinstance(article_body, str) and len(article_body) > len(body):
                body = article_body
    if not published:
        for match in _META_DATE_RE.finditer(page):
            published = match.group(1)
            break
    paragraphs = []
    for raw in _PARAGRAPH_RE.findall(page):
        text = strip_html(raw)
        if len(text) < 40 or len(text) > 1500:
            continue
        if any(marker in text for marker in _NOISE_MARKERS):
            continue
        letters = sum(1 for char in text if char.isalpha())
        if letters < len(text) * 0.6:
            continue
        paragraphs.append(text)
    extracted = " ".join(paragraphs)
    if len(extracted) > len(body):
        body = extracted
    return {
        "body": re.sub(r"\s+", " ", body).strip(),
        "published": published,
        "modified": modified,
    }


def fetch_article(item: dict, trading_date: date, session: Session) -> dict | None:
    try:
        page = session.get_text(item["link"], timeout=25, attempts=2)
    except Exception as error:
        print(f"Article unavailable ({item['label']}): {error}")
        return None
    details = extract_article(page)
    same_day = (
        matches_trading_date(item.get("published"), trading_date)
        or matches_trading_date(details["published"], trading_date)
        or matches_trading_date(details["modified"], trading_date)
    )
    if not same_day:
        return None
    body = details["body"]
    if len(body) < max(120, len(item.get("description", ""))):
        body = item.get("description", "")
    if len(body) < 80:
        return None
    return {"body": body, "published": details["published"] or item.get("published", "")}


def sources_from_feeds(trading_date: date, session: Session, feeds=None) -> list:
    items = collect_feed_items(trading_date, session, feeds)
    sources = []
    hebrew_fetched = 0
    english_fetched = 0
    for item in items:
        origin = "rss"
        content = item["description"]
        published = item["published"]
        wants_body = (
            (item["lang"] == "he" and hebrew_fetched < MAX_HEBREW_ARTICLES)
            or (item["label"] == "Yahoo Finance" and english_fetched < MAX_ENGLISH_ARTICLES)
        )
        if wants_body:
            article = fetch_article(item, trading_date, session)
            if item["lang"] == "he":
                hebrew_fetched += 1
            else:
                english_fetched += 1
            time.sleep(0.8)
            if article:
                content = article["body"]
                published = article["published"] or published
                origin = "article"
        if len(content) < 60:
            content = item["title"]
        sources.append(
            make_source(
                kind="news",
                label=item["label"],
                title=item["title"],
                url=item["link"],
                published=str(published),
                content=content,
                lang=item["lang"],
                score=item["score"] + (3 if origin == "article" else 0),
                origin=origin,
            )
        )
    return sources


def search_specs(trading_date: date, leader_name: str | None) -> list:
    month_day_year = trading_date.strftime("%B %-d %Y")
    day_month_year = trading_date.strftime("%-d/%-m/%Y")
    hebrew_domains = NEWS_DOMAINS[:4]
    specs = [
        {
            "kind": "market_close",
            "query": f"stock market close {month_day_year} S&P 500 Nasdaq Dow Jones Europe DAX FTSE closing levels",
            "topic": "news",
            "domains": NEWS_DOMAINS + ["finance.yahoo.com"],
        },
        {
            "kind": "macro",
            "query": f"US economic data released {month_day_year} ADP employment report Empire State manufacturing index actual reading",
            "topic": "news",
            "domains": NEWS_DOMAINS + ["investing.com"],
        },
        {
            "kind": "central_banks",
            "query": f"interest rate decision announced {month_day_year} Federal Reserve Bank of Israel ECB decided rate",
            "topic": "news",
            "domains": NEWS_DOMAINS + ["investing.com"],
        },
        {
            "kind": "earnings",
            "query": f"earnings results reported {month_day_year} after the bell revenue profit beat miss shares reaction",
            "topic": "news",
            "domains": NEWS_DOMAINS + ["finance.yahoo.com"],
        },
        {
            "kind": "movers",
            "query": f"stocks biggest movers {month_day_year} shares surged plunged why",
            "topic": "news",
            "domains": NEWS_DOMAINS + ["finance.yahoo.com"],
        },
        {
            "kind": "hebrew_markets",
            "query": f'סיכום המסחר בוול סטריט {day_month_year} נאסד"ק S&P דוחות ריבית נפט זהב',
            "topic": "news",
            "domains": hebrew_domains,
        },
        {
            "kind": "hebrew_macro",
            "query": f'נתוני מאקרו ארה"ב {day_month_year} ADP תעסוקה אמפייר סטייט הפד ריבית בנק ישראל',
            "topic": "news",
            "domains": hebrew_domains,
        },
    ]
    if leader_name:
        specs.append(
            {
                "kind": "leader_reason",
                "query": f"{leader_name} stock jumps {month_day_year} why shares rose",
                "topic": "news",
                "domains": NEWS_DOMAINS + ["finance.yahoo.com"],
            }
        )
    for spec in specs:
        spec["date"] = trading_date.isoformat()
    return specs


def tavily_search(spec: dict, api_key: str, session: Session) -> list:
    trading_date = date.fromisoformat(spec["date"])
    response = session.post_json(
        "https://api.tavily.com/search",
        {
            "query": spec["query"],
            "topic": spec["topic"],
            "search_depth": "advanced",
            "max_results": 8,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
            "include_domains": spec["domains"],
            "start_date": trading_date.isoformat(),
            "end_date": (trading_date + timedelta(days=1)).isoformat(),
        },
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=100,
        attempts=2,
    )
    results = []
    for result in response.get("results") or []:
        results.append(
            {
                "title": result.get("title"),
                "url": result.get("url"),
                "content": result.get("content"),
                "published": result.get("published_date") or result.get("publishedDate"),
                "score": result.get("score"),
            }
        )
    return results


def exa_search(spec: dict, api_key: str, session: Session) -> list:
    trading_date = date.fromisoformat(spec["date"])
    start = datetime.combine(trading_date, datetime_time.min, tzinfo=ISRAEL_TZ).astimezone(timezone.utc)
    end = datetime.combine(trading_date + timedelta(days=1), datetime_time.min, tzinfo=ISRAEL_TZ).astimezone(timezone.utc)
    response = session.post_json(
        "https://api.exa.ai/search",
        {
            "query": spec["query"],
            "type": "auto",
            "numResults": 8,
            "includeDomains": spec["domains"],
            "startPublishedDate": start.isoformat(),
            "endPublishedDate": end.isoformat(),
            "contents": {"text": {"maxCharacters": 2400}, "highlights": True},
        },
        headers={"x-api-key": api_key},
        timeout=100,
        attempts=2,
    )
    results = []
    for result in response.get("results") or []:
        content = str(result.get("text") or "").strip()
        if not content:
            content = " ".join(str(item) for item in result.get("highlights") or []).strip()
        results.append(
            {
                "title": result.get("title"),
                "url": result.get("url"),
                "content": content,
                "published": result.get("publishedDate"),
                "score": result.get("score"),
            }
        )
    return results


def normalize_search_result(result: dict, kind: str, trading_date: date, origin: str) -> dict | None:
    title = str(result.get("title") or "").strip()
    url = str(result.get("url") or "").strip()
    content = str(result.get("content") or "").strip()
    if not title or not url or len(content) < 80:
        return None
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        return None
    domain = normalized_domain(url)
    if not is_allowed_domain(domain):
        return None
    if not matches_trading_date(result.get("published"), trading_date):
        return None
    lang = "he" if re.search(r"[א-ת]", title + content[:200]) else "en"
    try:
        score = float(result.get("score") or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    return make_source(
        kind=kind,
        label=domain_label(domain),
        title=title,
        url=url,
        published=str(result.get("published")),
        content=content,
        lang=lang,
        score=score + 2,
        origin=origin,
    )


def sources_from_search(trading_date: date, leader_name: str | None, tavily_key: str,
                        exa_key: str, session: Session) -> list:
    if not tavily_key and not exa_key:
        print("No search API keys configured; skipping Tavily and Exa.")
        return []
    specs = search_specs(trading_date, leader_name)
    collected = []
    seen = set()

    def absorb(results, kind, origin, limit):
        accepted = 0
        for result in results:
            source = normalize_search_result(result, kind, trading_date, origin)
            if not source:
                continue
            key = canonical_url(source["url"])
            if key in seen:
                continue
            seen.add(key)
            collected.append(source)
            accepted += 1
            if accepted >= limit:
                break
        return accepted

    if tavily_key:
        for spec in specs:
            try:
                results = tavily_search(spec, tavily_key, session)
            except Exception as error:
                print(f"Tavily warning for {spec['kind']}: {error}")
                continue
            accepted = absorb(results, spec["kind"], "tavily", 3)
            print(f"Tavily {spec['kind']}: {len(results)} results, {accepted} accepted")
    if exa_key and len(collected) < 8:
        print("Few date-verified Tavily results; querying Exa as well.")
        for spec in specs:
            try:
                results = exa_search(spec, exa_key, session)
            except Exception as error:
                print(f"Exa warning for {spec['kind']}: {error}")
                continue
            accepted = absorb(results, spec["kind"], "exa", 2)
            print(f"Exa {spec['kind']}: {len(results)} results, {accepted} accepted")
    return collected


def number_sources(sources: list) -> list:
    ranked = sorted(
        sources,
        key=lambda item: (
            0 if item["origin"] == "article" else 1 if item["origin"] in {"tavily", "exa"} else 2,
            -float(item.get("score") or 0),
        ),
    )
    trimmed = []
    seen = set()
    total = 0
    for source in ranked:
        key = canonical_url(source["url"])
        if key in seen:
            continue
        if len(trimmed) >= MAX_SOURCES or total + len(source["content"]) > MAX_TOTAL_CHARS:
            continue
        seen.add(key)
        total += len(source["content"])
        trimmed.append(source)
    for index, source in enumerate(trimmed, start=1):
        source["id"] = index
    return trimmed


def collect_sources(trading_date: date, *, tavily_key: str = "", exa_key: str = "",
                    leader_name: str | None = None, session: Session | None = None) -> list:
    session = session or Session(delays=(4, 10), rate_limit_delay=10)
    feed_sources = sources_from_feeds(trading_date, session)
    print(f"Feed sources verified for {trading_date}: {len(feed_sources)}")
    search_sources = sources_from_search(trading_date, leader_name, tavily_key, exa_key, session)
    print(f"Search sources verified for {trading_date}: {len(search_sources)}")
    return number_sources(feed_sources + search_sources)


def source_material(sources: list) -> str:
    blocks = []
    for source in sources:
        blocks.append(
            f"[S{source['id']}]\n"
            f"מקור: {source['label']}\n"
            f"כותרת: {source['title']}\n"
            f"תאריך פרסום: {source['published']}\n"
            f"תוכן:\n{source['content']}"
        )
    return "\n\n".join(blocks)


def fixture_sources(trading_date: date) -> list:
    """Offline stand-ins used by tests and the offline dry run."""
    stamp = datetime.combine(trading_date, datetime_time(22, 30), tzinfo=ISRAEL_TZ).isoformat()
    sources = [
        make_source(
            kind="news", label="גלובס", title="עליות בוול סטריט; סנואופלייק מזנקת ב-23%, ברודקום נופלת ב-7%",
            url="https://www.globes.co.il/news/article.aspx?did=1001554302", published=stamp,
            content=(
                'וול סטריט ננעלה בעליות. מניות חברות התוכנה היו במוקד לאחר שסנואופלייק פרסמה '
                "תוצאות טובות מהצפוי לרבעון, והמניה זינקה בכ-23%. ברודקום פרסמה דוחות שעקפו את "
                "התחזיות אך המניה ירדה בכ-7% בעקבות תחזית מאכזבת. דוח ADP הצביע על תוספת של 38 "
                "אלף משרות בלבד באוגוסט, נמוך מהתחזיות."
            ),
            lang="he", score=9, origin="article",
        ),
        make_source(
            kind="news", label="TheMarker", title="הפד הותיר את הריבית ללא שינוי",
            url="https://www.themarker.com/wallstreet/example", published=stamp,
            content="הבנק הפדרלי הותיר את הריבית ללא שינוי בטווח של 4.25%-4.5%, בהתאם לתחזיות.",
            lang="he", score=7, origin="article",
        ),
    ]
    return number_sources(sources)
