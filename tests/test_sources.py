import unittest
from datetime import date

from mivzak import sources


FEED = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>test</title>
<item><title>עליות בוול סטריט; סנואופלייק מזנקת ב-23%</title>
<link>https://www.globes.co.il/news/article.aspx?did=1#utm_source=RSS</link>
<description><![CDATA[נאסד"ק עולה ב-0.6% &#8226; מחירי הנפט עולים]]></description>
<pubDate>Thu, 03 Sep 2026 14:22:00 GMT</pubDate></item>
<item><title>כתבה ישנה על נדל"ן</title>
<link>https://www.globes.co.il/news/article.aspx?did=2</link>
<description>דירות</description>
<pubDate>Mon, 31 Aug 2026 10:03:00 GMT</pubDate></item>
<item><title>Adobe stock drops after CEO news</title>
<link>https://example.com/story</link>
<description>stocks</description>
<pubDate>Thu, 03 Sep 2026 15:00:00 GMT</pubDate></item>
</channel></rss>"""

ARTICLE = """<html><head>
<script type="application/ld+json">{"@type":"NewsArticle","datePublished":"2026-09-03T07:04:00.000","dateModified":"2026-09-04T00:38:15.000","articleBody":""}</script>
</head><body>
<p>וול סטריט ננעלה הלילה בעליות חדות לנוכח הירידה בהסתברות להעלאת ריבית של הפד - נאסד"ק עלה ב-1.4%, S&P 500 ב-1% ודאו ג'ונס ב-1.2%.</p>
<p>window.dataLayer = window.dataLayer || [];</p>
<p>קצר</p>
<p>מניות חברות התוכנה היו במוקד לאחר שסנואופלייק פרסמה תוצאות טובות מהצפוי, כאשר מנכ"ל החברה ייחס את הביצועים לאימוץ הגובר של מוצרי הבינה המלאכותית.</p>
</body></html>"""


class FakeSession:
    def __init__(self, pages):
        self.pages = pages

    def get_text(self, url, **kwargs):
        if url not in self.pages:
            raise RuntimeError("unavailable " + url)
        return self.pages[url]


class SourceTests(unittest.TestCase):
    def test_dates(self):
        trading_date = date(2026, 9, 3)
        self.assertTrue(sources.matches_trading_date("Thu, 03 Sep 2026 22:30:00 GMT", trading_date))
        self.assertTrue(sources.matches_trading_date("2026-09-03T07:04:00.000", trading_date))
        self.assertTrue(sources.matches_trading_date("2026-09-04T00:38:15+03:00", trading_date))  # still 3.9 in New York
        self.assertFalse(sources.matches_trading_date("2026-09-02T10:00:00Z", trading_date))
        self.assertFalse(sources.matches_trading_date("", trading_date))

    def test_parse_feed_and_filtering(self):
        session = FakeSession({"feed": FEED})
        items = sources.collect_feed_items(date(2026, 9, 3), session, feeds=[("גלובס", "feed", "he", "markets")])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["link"], "https://www.globes.co.il/news/article.aspx?did=1")
        self.assertGreaterEqual(items[0]["score"], 5)

    def test_extract_article(self):
        details = sources.extract_article(ARTICLE)
        self.assertIn("וול סטריט ננעלה הלילה", details["body"])
        self.assertIn("סנואופלייק", details["body"])
        self.assertNotIn("dataLayer", details["body"])
        self.assertEqual(details["published"], "2026-09-03T07:04:00.000")

    def test_sources_from_feeds_uses_article_body(self):
        session = FakeSession({"feed": FEED, "https://www.globes.co.il/news/article.aspx?did=1": ARTICLE})
        result = sources.sources_from_feeds(date(2026, 9, 3), session, feeds=[("גלובס", "feed", "he", "markets")])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["origin"], "article")
        self.assertIn("סנואופלייק", result[0]["content"])
        numbered = sources.number_sources(result)
        self.assertEqual(numbered[0]["id"], 1)
        self.assertIn("[S1]", sources.source_material(numbered))

    def test_normalize_search_result(self):
        trading_date = date(2026, 9, 3)
        good = sources.normalize_search_result(
            {"title": "Fed holds rates", "url": "https://www.marketwatch.com/story/x", "content": "x" * 100,
             "published": "2026-09-03T20:00:00Z", "score": 0.5},
            "central_banks", trading_date, "tavily",
        )
        self.assertIsNotNone(good)
        self.assertEqual(good["label"], "MarketWatch")
        bad_domain = sources.normalize_search_result(
            {"title": "t", "url": "https://example.com/x", "content": "x" * 100, "published": "2026-09-03"},
            "macro", trading_date, "tavily",
        )
        self.assertIsNone(bad_domain)
        wrong_day = sources.normalize_search_result(
            {"title": "t", "url": "https://www.globes.co.il/x", "content": "x" * 100, "published": "2026-09-02"},
            "macro", trading_date, "tavily",
        )
        self.assertIsNone(wrong_day)

    def test_search_specs(self):
        specs = sources.search_specs(date(2026, 9, 3), "Snowflake")
        self.assertEqual(specs[-1]["kind"], "leader_reason")
        self.assertTrue(all(spec["date"] == "2026-09-03" for spec in specs))


if __name__ == "__main__":
    unittest.main()
