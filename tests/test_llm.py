import unittest
from datetime import date

from mivzak.llm import build_prompt, validate_paragraphs
from mivzak.narration import Paragraph
from mivzak.sources import fixture_sources


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.sources = fixture_sources(date(2026, 9, 3))
        self.existing = [
            Paragraph("us_close", "המסחר בוול סטריט ננעל אמש במגמה חיובית. מדד ה-S&P 500 עלה במחצית האחוז."),
        ]

    def test_accepts_and_converts_digits(self):
        report = {
            "paragraphs": [
                {
                    "category": "macro",
                    "text": 'בגזרת המאקרו, דו"ח התעסוקה של ה-ADP בארה"ב הצביע בחודש אוגוסט על תוספת של 38 אלף מועסקים בלבד, נמוך מהתחזיות המוקדמות.',
                    "source_ids": [1],
                },
                {
                    "category": "earnings",
                    "text": "במסגרת עונת הדוחות, סנואופלייק פרסמה אמש תוצאות טובות מהצפוי והמניה זינקה ב-23%, בעוד ברודקום ירדה ב-7% בעקבות תחזית מאכזבת.",
                    "source_ids": [1],
                },
            ]
        }
        accepted, errors = validate_paragraphs(report, self.sources, self.existing, "Snowflake")
        self.assertEqual(errors, [])
        self.assertEqual(len(accepted), 2)
        self.assertIn("שלושים ושמונה אלף מועסקים", accepted[0].text)
        self.assertIn("בכעשרים ושלושה אחוזים", accepted[1].text)
        self.assertIn("בכשבעה אחוזים", accepted[1].text)
        self.assertEqual(accepted[0].source_ids, [1])
        self.assertEqual(accepted[0].origin, "llm")

    def test_rejections(self):
        report = {
            "paragraphs": [
                {"category": "macro", "text": "קצר מדי.", "source_ids": [1]},
                {"category": "movers", "text": "מניית X ירדה אמש בחדות לאחר פרסום הדוחות ทดสอบ בתגובה לתחזית.", "source_ids": [1]},
                {"category": "central_banks", "text": "הפד הותיר אמש את הריבית ללא שינוי בטווח של ארבעה ורבע עד ארבעה וחצי אחוזים, בהתאם לתחזיות.", "source_ids": []},
                {"category": "earnings", "text": "המסחר בוול סטריט ננעל אמש במגמה חיובית. הדוחות של ברודקום הכו את התחזיות בשורת ההכנסות.", "source_ids": [1]},
                {"category": "leader_reason", "text": "הזינוק הגיע על רקע חוזה חדש עם לקוח גדול בתחום הבינה המלאכותית.", "source_ids": [1]},
                {"category": "macro", "text": "מדד המחירים לצרכן עלה היום בשלוש עשיריות האחוז, בהתאם לתחזיות המוקדמות.", "source_ids": [2]},
                {"category": "unknown", "text": "טקסט ארוך מספיק כדי לעבור את בדיקת האורך של הפסקה במערכת.", "source_ids": [1]},
            ]
        }
        accepted, errors = validate_paragraphs(report, self.sources, self.existing, None)
        self.assertEqual(accepted, [])
        joined = "\n".join(errors)
        self.assertIn("אורך", joined)
        self.assertIn("תווים משפה", joined)
        self.assertIn("אין מקור", joined)
        self.assertIn("משפט שכבר מופיע", joined)
        self.assertIn("leader_reason", joined)
        self.assertIn("'היום'", joined)
        self.assertIn("קטגוריה לא חוקית", joined)

    def test_prompt_mentions_rules_and_sources(self):
        prompt = build_prompt(date(2026, 9, 3), date(2026, 9, 4), self.sources, "- משפט קיים", "Snowflake")
        self.assertIn("[S1]", prompt)
        self.assertIn("Snowflake", prompt)
        self.assertIn("2026-09-03", prompt)
        self.assertIn("במילים", prompt)


if __name__ == "__main__":
    unittest.main()
