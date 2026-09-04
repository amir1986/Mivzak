import unittest

from mivzak import hebrew_numbers as hn


class CardinalTests(unittest.TestCase):
    def test_small_masculine(self):
        self.assertEqual(hn.cardinal(1), "אחד")
        self.assertEqual(hn.cardinal(2), "שניים")
        self.assertEqual(hn.cardinal(2, noun_follows=True), "שני")
        self.assertEqual(hn.cardinal(11), "אחד עשר")
        self.assertEqual(hn.cardinal(21), "עשרים ואחד")
        self.assertEqual(hn.cardinal(38), "שלושים ושמונה")

    def test_small_feminine(self):
        self.assertEqual(hn.cardinal(2, "f", noun_follows=True), "שתי")
        self.assertEqual(hn.cardinal(3, "f"), "שלוש")
        self.assertEqual(hn.cardinal(12, "f"), "שתים עשרה")
        self.assertEqual(hn.cardinal(21, "f"), "עשרים ואחת")

    def test_hundreds_and_thousands(self):
        self.assertEqual(hn.cardinal(100), "מאה")
        self.assertEqual(hn.cardinal(105), "מאה וחמישה")
        self.assertEqual(hn.cardinal(123), "מאה עשרים ושלושה")
        self.assertEqual(hn.cardinal(1000), "אלף")
        self.assertEqual(hn.cardinal(2026, "f"), "אלפיים עשרים ושש")
        self.assertEqual(hn.cardinal(4480), "ארבעת אלפים ארבע מאות ושמונים")
        self.assertEqual(hn.cardinal(7666, "f"), "שבעת אלפים שש מאות שישים ושש")
        self.assertEqual(hn.cardinal(38000), "שלושים ושמונה אלף")
        self.assertEqual(hn.cardinal(11000), "אחד עשר אלף")
        self.assertEqual(hn.cardinal(250000), "מאתיים וחמישים אלף")

    def test_millions_and_billions(self):
        self.assertEqual(hn.cardinal(1_000_000), "מיליון")
        self.assertEqual(hn.cardinal(2_000_000), "שני מיליון")
        self.assertEqual(hn.cardinal(1_200_000), "מיליון ומאתיים אלף")
        self.assertEqual(hn.cardinal(13_000_000_000), "שלושה עשר מיליארד")
        self.assertEqual(hn.cardinal(2_300_000_000), "שני מיליארד ושלוש מאות מיליון")


class PercentTests(unittest.TestCase):
    def test_ibi_examples(self):
        self.assertEqual(hn.percent_phrase(0.5), "במחצית האחוז")
        self.assertEqual(hn.percent_phrase(0.4, ""), "ארבע עשיריות האחוז")
        self.assertEqual(hn.percent_phrase(0.8), "בשמונה עשיריות האחוז")
        self.assertEqual(hn.percent_phrase(1.2), "באחוז ושתי עשיריות")
        self.assertEqual(hn.percent_phrase(-1.5, ""), "אחוז וחצי")
        self.assertEqual(hn.percent_phrase(7.2), "בשבעה אחוזים ושתי עשיריות")
        self.assertEqual(hn.percent_phrase(-5.5), "בחמישה וחצי אחוזים")
        self.assertEqual(hn.percent_phrase(5.5, approximate=True), "בכחמישה וחצי אחוזים")

    def test_edges(self):
        self.assertIsNone(hn.percent_phrase(0.03))
        self.assertEqual(hn.percent_phrase(0.1), "בעשירית האחוז")
        self.assertEqual(hn.percent_phrase(0.24), "בשתי עשיריות האחוז")
        self.assertEqual(hn.percent_phrase(0.97), "באחוז")
        self.assertEqual(hn.percent_phrase(1.1), "באחוז ועשירית")
        self.assertEqual(hn.percent_phrase(1.3), "באחוז ושלוש עשיריות")
        self.assertEqual(hn.percent_phrase(2.0), "בשני אחוזים")
        self.assertEqual(hn.percent_phrase(2.3), "בשני אחוזים ושלוש עשיריות")
        self.assertEqual(hn.percent_phrase(3.1), "בשלושה אחוזים ועשירית")
        self.assertEqual(hn.percent_phrase(9.8), "בתשעה אחוזים ושמונה עשיריות")
        self.assertEqual(hn.percent_phrase(9.96), "בכעשרה אחוזים")
        self.assertEqual(hn.percent_phrase(17.35), "בכשבעה עשר אחוזים")
        self.assertEqual(hn.percent_phrase(23.4), "בכעשרים ושלושה אחוזים")


class RatesAndPricesTests(unittest.TestCase):
    def test_basis_points(self):
        self.assertIsNone(hn.basis_points_phrase(0.3))
        self.assertEqual(hn.basis_points_phrase(1), "נקודת בסיס אחת")
        self.assertEqual(hn.basis_points_phrase(-2), "שתי נקודות בסיס")
        self.assertEqual(hn.basis_points_phrase(3), "שלוש נקודות בסיס")
        self.assertEqual(hn.basis_points_phrase(11), "אחת עשרה נקודות בסיס")
        self.assertEqual(hn.basis_points_phrase(21), "עשרים ואחת נקודות בסיס")

    def test_yield_phrase(self):
        self.assertEqual(hn.yield_phrase(4.72), "ארבעה אחוזים ושבעים ושתיים מאיות")
        self.assertEqual(hn.yield_phrase(4.59), "ארבעה אחוזים וחמישים ותשע מאיות")
        self.assertEqual(hn.yield_phrase(4.2), "ארבעה אחוזים ושתי עשיריות")
        self.assertEqual(hn.yield_phrase(4.5), "ארבעה אחוזים וחצי")
        self.assertEqual(hn.yield_phrase(4.25), "ארבעה אחוזים ורבע")
        self.assertEqual(hn.yield_phrase(4.0), "ארבעה אחוזים")
        self.assertEqual(hn.yield_phrase(1.0), "אחוז אחד")
        self.assertEqual(hn.yield_phrase(1.5), "אחוז וחצי")
        self.assertEqual(hn.yield_phrase(0.4), "ארבע עשיריות האחוז")
        self.assertEqual(hn.yield_phrase(3.999), "ארבעה אחוזים")

    def test_dollars_and_points(self):
        self.assertEqual(hn.dollars_phrase(91.3), "תשעים ואחד דולרים")
        self.assertEqual(hn.dollars_phrase(89.52), "תשעים דולרים")
        self.assertEqual(hn.dollars_phrase(2), "שני דולרים")
        self.assertEqual(hn.dollars_phrase(1), "דולר אחד")
        self.assertEqual(
            hn.dollars_phrase(4481.1, step=10, approximate=True),
            "כארבעת אלפים ארבע מאות ושמונים דולרים",
        )
        self.assertEqual(hn.decimal_points_phrase(20.6), "עשרים נקודה שש נקודות")
        self.assertEqual(hn.decimal_points_phrase(19.6), "תשע עשרה נקודה שש נקודות")
        self.assertEqual(hn.decimal_points_phrase(-5.5), "מינוס חמש נקודה חמש נקודות")
        self.assertEqual(hn.decimal_points_phrase(12.0), "שתים עשרה נקודות")

    def test_counts_and_scaled(self):
        self.assertEqual(hn.count_phrase(38000, "מועסק", "מועסקים"), "שלושים ושמונה אלף מועסקים")
        self.assertEqual(hn.count_phrase(1, "מועסק", "מועסקים"), "מועסק אחד")
        self.assertEqual(hn.count_phrase(2, "נקודה", "נקודות", "f"), "שתי נקודות")
        self.assertEqual(hn.scaled_amount_phrase(38, "אלף"), "שלושים ושמונה אלף")
        self.assertEqual(hn.scaled_amount_phrase(13, "מיליארד"), "שלושה עשר מיליארד")
        self.assertEqual(hn.scaled_amount_phrase(2.5, "מיליארד"), "שניים וחצי מיליארד")
        self.assertEqual(hn.scaled_amount_phrase(1.5, "מיליון"), "מיליון וחצי")
        self.assertEqual(hn.scaled_amount_phrase(1.2, "מיליון"), "מיליון ומאתיים אלף")
        self.assertEqual(hn.scaled_amount_phrase(600, "מיליון"), "שש מאות מיליון")
        self.assertEqual(hn.scaled_amount_phrase(5, "אלפים"), "חמשת אלפים")


class DigitsToWordsTests(unittest.TestCase):
    def test_percent_with_prefixes(self):
        self.assertEqual(hn.digits_to_words("המניה ירדה ב-5.5%"), "המניה ירדה בחמישה וחצי אחוזים")
        self.assertEqual(hn.digits_to_words("ירדה בכ-5.5%"), "ירדה בכחמישה וחצי אחוזים")
        self.assertEqual(hn.digits_to_words("עלה ב-0.4%"), "עלה בארבע עשיריות האחוז")
        self.assertEqual(hn.digits_to_words("התשואה ירדה ל-4.77%"), "התשואה ירדה לארבעה אחוזים ושבעים ושבע מאיות")
        self.assertEqual(hn.digits_to_words("זינקה בכ-23%"), "זינקה בכעשרים ושלושה אחוזים")
        self.assertEqual(hn.digits_to_words("זינקה ב-7.2%"), "זינקה בשבעה אחוזים ושתי עשיריות")
        self.assertEqual(hn.digits_to_words("עלייה של 1.4%"), "עלייה של אחוז וארבע עשיריות")
        self.assertEqual(hn.digits_to_words("של 0.46 אחוזים"), "של מחצית האחוז")

    def test_money_points_and_scaled(self):
        self.assertEqual(hn.digits_to_words("רכישה ב-13 מיליארד דולר"), "רכישה בשלושה עשר מיליארד דולר")
        self.assertEqual(hn.digits_to_words("תוספת של 38 אלף מועסקים"), "תוספת של שלושים ושמונה אלף מועסקים")
        self.assertEqual(hn.digits_to_words("בשווי כ-600 מיליון דולרים"), "בשווי כשש מאות מיליון דולרים")
        self.assertEqual(hn.digits_to_words("נסחר סביב 95.25 דולר לחבית"), "נסחר סביב תשעים וחמישה דולרים לחבית")
        self.assertEqual(hn.digits_to_words("לרמה של 7,666 נקודות"), "לרמה של שבעת אלפים שש מאות שישים ושש נקודות")
        self.assertEqual(hn.digits_to_words("לרמה של 20.6 נקודות"), "לרמה של עשרים נקודה שש נקודות")
        self.assertEqual(hn.digits_to_words("ירדה ב-3 נקודות בסיס"), "ירדה בשלוש נקודות בסיס")
        self.assertEqual(hn.digits_to_words("אג\"ח ל-10 שנים"), "אג\"ח לעשר שנים")
        self.assertEqual(hn.digits_to_words("הכנסות של 2.5 מיליארד"), "הכנסות של שניים וחצי מיליארד")

    def test_names_and_years_untouched(self):
        text = "מדד ה-S&P 500 עלה, וגם FTSE 100 ומדד ת\"א 35 עלו ב-2026"
        self.assertEqual(hn.digits_to_words(text), text)
        self.assertEqual(hn.remaining_digit_tokens(text), [])
        self.assertTrue(hn.remaining_digit_tokens("המניה עלתה 12 דולר-ים"))


if __name__ == "__main__":
    unittest.main()
