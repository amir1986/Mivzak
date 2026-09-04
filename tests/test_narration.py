import unittest
from datetime import date

from mivzak.market_data import MarketSnapshot, fixture_snapshot
from mivzak.narration import (
    CATEGORY_ORDER,
    Paragraph,
    build_data_paragraphs,
    move_clause,
    order_paragraphs,
    sentence_fingerprints,
    styler_for,
    trend_word,
)


class NarrationTests(unittest.TestCase):
    def setUp(self):
        self.trading_date = date(2026, 9, 3)
        self.snapshot = fixture_snapshot(self.trading_date)
        self.paragraphs = build_data_paragraphs(self.snapshot, self.trading_date)

    def test_all_categories_present_in_template_order(self):
        categories = [paragraph.category for paragraph in self.paragraphs]
        self.assertEqual(
            categories,
            ["us_close", "sectors", "rates", "commodities", "leader", "europe_close"],
        )
        ordered = order_paragraphs(list(reversed(self.paragraphs)))
        self.assertEqual([paragraph.category for paragraph in ordered], categories)

    def test_template_phrases_and_no_digits(self):
        texts = {paragraph.category: paragraph.text for paragraph in self.paragraphs}
        self.assertTrue(texts["us_close"].startswith("המסחר בוול סטריט ננעל אמש במגמה חיובית."))
        self.assertIn("מדד ה-S&P 500", texts["us_close"])
        self.assertIn("בגזרת הסחורות, מחיר חבית נפט מסוג WTI", texts["commodities"])
        self.assertIn("תשעים ואחד דולרים לחבית", texts["commodities"])
        self.assertTrue(texts["europe_close"].startswith("באירופה, המסחר ננעל אמש בירידות שערים."))
        self.assertIn("Snowflake", texts["leader"])
        self.assertIn("כעשרים ושלושה אחוזים", texts["leader"])
        self.assertIn("Lululemon", texts["leader"])
        self.assertIn("ארבעה אחוזים ושבעים ושש מאיות", texts["rates"])
        for paragraph in self.paragraphs:
            self.assertNotIn("בב", paragraph.text, paragraph.text)
            stripped = paragraph.text.replace("S&P 500", "").replace("50", "")
            self.assertFalse(any(char.isdigit() for char in stripped), paragraph.text)

    def test_wording_varies_between_days(self):
        other = build_data_paragraphs(self.snapshot, date(2026, 9, 7))
        self.assertNotEqual(other[0].text, self.paragraphs[0].text)

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

    def test_holiday_and_missing_data(self):
        empty = MarketSnapshot(trading_date=self.trading_date)
        self.assertEqual(build_data_paragraphs(empty, self.trading_date), [])
        holiday = MarketSnapshot(trading_date=self.trading_date, us_market_closed=True)
        paragraphs = build_data_paragraphs(holiday, self.trading_date)
        self.assertEqual(paragraphs[0].category, "us_close")
        self.assertIn("יום חג", paragraphs[0].text)

    def test_fingerprints(self):
        prints = sentence_fingerprints("המסחר בוול סטריט ננעל אמש במגמה חיובית. קצר.")
        self.assertEqual(len(prints), 1)
        self.assertEqual(len(CATEGORY_ORDER), 10)
        self.assertIsInstance(Paragraph("x", "y").as_dict(), dict)


if __name__ == "__main__":
    unittest.main()
