import os
import unittest
from datetime import date, datetime, time as datetime_time

from mivzak.config import NEW_YORK_TZ
from mivzak.market_data import MarketSnapshot, Quote, fixture_snapshot
from mivzak.narration import (
    CATEGORY_ORDER,
    Paragraph,
    build_data_paragraphs,
    move_clause,
    order_paragraphs,
    sentence_fingerprints,
    styler_for,
    trend_word,
    when_phrase,
)


class NarrationTests(unittest.TestCase):
    def setUp(self):
        self.trading_date = date(2026, 9, 3)
        self.snapshot = fixture_snapshot(self.trading_date)
        self.paragraphs = build_data_paragraphs(self.snapshot, self.trading_date)
        self.texts = {paragraph.category: paragraph.text for paragraph in self.paragraphs}

    def test_categories_in_template_order(self):
        categories = [paragraph.category for paragraph in self.paragraphs]
        self.assertEqual(categories, ["us_close", "rates", "commodities", "leader", "europe_close"])
        ordered = order_paragraphs(list(reversed(self.paragraphs)))
        self.assertEqual([paragraph.category for paragraph in ordered], categories)

    def test_wall_street_block_has_two_lines_without_dow(self):
        lines = self.texts["us_close"].split("\n")
        self.assertEqual(lines[0], "המסחר בוול סטריט ננעל אמש במגמה חיובית.")
        self.assertIn("מדד ה-S&P 500", lines[1])
        self.assertIn('מדד הנאסד"ק', lines[1])
        self.assertNotIn("דאו", lines[1])
        self.assertIn("מחצית האחוז", lines[1])
        self.assertIn("ארבע עשיריות האחוז", lines[1])

    def test_rates_commodities_leader_europe(self):
        self.assertTrue(self.texts["rates"].startswith('באפיק אג"ח חו"ל, התשואה על אג"ח מדינה ארה"ב לעשר שנים ירדה אמש בשלוש נקודות בסיס'))
        self.assertIn("ארבעה אחוזים ושבעים ושש מאיות", self.texts["rates"])
        self.assertTrue(self.texts["commodities"].startswith("בגזרת הסחורות, מחיר חבית נפט מסוג WTI"))
        self.assertIn("תשעים ואחד דולרים לחבית", self.texts["commodities"])
        self.assertNotIn("זהב", self.texts["commodities"])  # gold moved less than half a percent
        leader_lines = self.texts["leader"].split("\n")
        self.assertEqual(leader_lines[0], "מניית Snowflake זינקה אמש בכעשרים ושלושה אחוזים.")
        self.assertEqual(leader_lines[1], "מנגד, מניית Lululemon Athletica צנחה אמש בכשבעה עשר אחוזים.")
        europe_lines = self.texts["europe_close"].split("\n")
        self.assertIn(europe_lines[0], {"באירופה, המסחר ננעל אמש בירידות שערים.", "באירופה, המסחר ננעל אמש במגמה שלילית."})
        self.assertEqual(europe_lines[1], "באסיה, המדדים המובילים ננעלו אמש במגמה דומה.")
        for paragraph in self.paragraphs:
            self.assertNotIn("בב", paragraph.text, paragraph.text)
            stripped = paragraph.text.replace("S&P 500", "")
            self.assertFalse(any(char.isdigit() for char in stripped), paragraph.text)

    def test_friday_uses_weekend_wording(self):
        friday = date(2026, 9, 4)
        self.assertEqual(when_phrase(friday), "בסוף השבוע")
        paragraphs = build_data_paragraphs(fixture_snapshot(friday), friday)
        self.assertTrue(paragraphs[0].text.startswith("המסחר בוול סטריט ננעל בסוף השבוע במגמה חיובית."))
        self.assertIn("בסוף השבוע", paragraphs[-1].text)

    def test_wording_varies_between_days(self):
        texts = {
            build_data_paragraphs(self.snapshot, date(2026, 9, 7 + offset))[0].text
            for offset in range(3)
        }
        self.assertGreater(len(texts), 1)

    def test_gold_and_big_yield_move(self):
        snapshot = fixture_snapshot(self.trading_date)
        gold = snapshot.quotes["GC=F"]
        snapshot.quotes["GC=F"] = Quote(
            gold.symbol, gold.label, gold.kind, 4491.7, 4366.3, 2.87, gold.market_time,
            gold.provider, gold.url, True,
        )
        tnx = snapshot.quotes["^TNX"]
        snapshot.quotes["^TNX"] = Quote(
            tnx.symbol, tnx.label, tnx.kind, 4.59, 4.48, 2.4, tnx.market_time, tnx.provider, tnx.url, True,
        )
        texts = {p.category: p.text for p in build_data_paragraphs(snapshot, self.trading_date)}
        self.assertIn("מחיר אונקיית הזהב", texts["commodities"])
        self.assertIn("כארבעת אלפים ארבע מאות ותשעים דולרים לאונקיה", texts["commodities"])
        self.assertTrue(texts["rates"].startswith('באפיק אג"ח חו"ל, נרשמו הפסדי הון, כאשר התשואה'))
        self.assertIn("זינקה אמש באחת עשרה נקודות בסיס", texts["rates"])
        self.assertIn("ארבעה אחוזים וחמישים ותשע מאיות", texts["rates"])

    def test_rates_threshold_and_sectors_flag(self):
        os.environ["MIVZAK_RATES_MIN_BP"] = "5"
        os.environ["MIVZAK_INCLUDE_SECTORS"] = "true"
        try:
            categories = [p.category for p in build_data_paragraphs(self.snapshot, self.trading_date)]
        finally:
            os.environ.pop("MIVZAK_RATES_MIN_BP", None)
            os.environ.pop("MIVZAK_INCLUDE_SECTORS", None)
        self.assertNotIn("rates", categories)
        self.assertIn("sectors", categories)

    def test_trend_and_move_clause(self):
        self.assertEqual(trend_word([0.5, 0.4, 0.3]), "חיובית")
        self.assertEqual(trend_word([-0.5, -0.4]), "שלילית")
        self.assertEqual(trend_word([0.5, -0.4]), "מעורבת")
        self.assertEqual(trend_word([0.01, -0.02]), "ללא שינוי")
        styler = styler_for(self.trading_date)
        self.assertEqual(move_clause(0.02, "m", styler), "סיים את היום כמעט ללא שינוי")
        clause = move_clause(0.8, "m", styler, adverb="אמש")
        self.assertIn("אמש", clause)
        self.assertIn("שמונה עשיריות האחוז", clause)
        self.assertNotIn("בב", clause)
        self.assertIn("אחוז ושתי עשיריות", move_clause(-1.2, "m", styler))

    def test_holiday_and_missing_data(self):
        empty = MarketSnapshot(trading_date=self.trading_date)
        self.assertEqual(build_data_paragraphs(empty, self.trading_date), [])
        holiday = MarketSnapshot(trading_date=self.trading_date, us_market_closed=True)
        paragraphs = build_data_paragraphs(holiday, self.trading_date)
        self.assertEqual(paragraphs[0].category, "us_close")
        self.assertIn("יום חג", paragraphs[0].text)

    def test_fingerprints_and_lines(self):
        prints = sentence_fingerprints("המסחר בוול סטריט ננעל אמש במגמה חיובית.\nקצר.")
        self.assertEqual(len(prints), 1)
        self.assertEqual(len(CATEGORY_ORDER), 10)
        paragraph = Paragraph("x", "שורה ראשונה\n\nשורה שנייה ")
        self.assertEqual(paragraph.lines, ["שורה ראשונה", "שורה שנייה"])
        self.assertIsInstance(paragraph.as_dict(), dict)


if __name__ == "__main__":
    unittest.main()
