import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from mivzak import __main__ as cli
from mivzak.config import CLOSING, ISRAEL_TZ, OPENING, PAUSE
from mivzak.market_data import fixture_snapshot
from mivzak.narration import Paragraph, build_data_paragraphs
from mivzak.render import docx_body_text, docx_filename, email_subject, render_docx, render_email, split_runs
from mivzak.state import already_sent, load_state, write_state


class RenderTests(unittest.TestCase):
    def test_split_runs(self):
        runs = split_runs("מדד ה-S&P 500 עלה, ומניית Aehr Test Systems זינקה.")
        self.assertEqual(
            runs,
            [("מדד ה-", False), ("S&P 500", True), (" עלה, ומניית ", False),
             ("Aehr Test Systems", True), (" זינקה.", False)],
        )

    def test_docx_lines_and_email(self):
        trading_date = date(2026, 9, 3)
        paragraphs = build_data_paragraphs(fixture_snapshot(trading_date), trading_date)
        expected_lines = [line for paragraph in paragraphs for line in paragraph.lines]
        self.assertGreater(len(expected_lines), len(paragraphs))  # multi-line blocks exist
        with tempfile.TemporaryDirectory() as folder:
            path = render_docx([p.text for p in paragraphs], trading_date + timedelta(days=1), Path(folder) / "out.docx")
            body = docx_body_text(path)
            self.assertEqual(body[:-1], expected_lines)
            self.assertEqual(body[-1], PAUSE)
            from docx import Document

            document = Document(str(path))
            cells = [cell.text for row in document.tables[0].rows for cell in row.cells]
            self.assertTrue(any(OPENING in text for text in cells))
            self.assertTrue(any(CLOSING in text for text in cells))
            xml = document.tables[0]._tbl.xml
            self.assertIn('w:highlight w:val="green"', xml)
            self.assertIn("<w:rtl/>", xml)
        plain, rich = render_email(trading_date, trading_date + timedelta(days=1), paragraphs, ["הערה"])
        self.assertIn(OPENING, plain)
        self.assertIn(CLOSING, rich)
        self.assertIn("הערה", rich)
        self.assertIn("finance.yahoo.com", rich)
        self.assertIn("<br>", rich)
        self.assertEqual(docx_filename(date(2026, 9, 4)), "מבזק בוקר 04.09.2026.docx")
        self.assertEqual(email_subject(date(2026, 9, 4)), "מבזק בוקר 04.09.2026")


class StateTests(unittest.TestCase):
    def test_marker_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.json"
            self.assertEqual(load_state(path), {})
            write_state(
                trading_date=date(2026, 9, 3), brief_date=date(2026, 9, 4), role="primary",
                recipient="HELLYBRACHA@GMAIL.COM", paragraph_texts=["a"], now=datetime.now(ISRAEL_TZ), path=path,
            )
            state = load_state(path)
            self.assertTrue(already_sent(state, date(2026, 9, 3), "hellybracha@gmail.com"))
            self.assertFalse(already_sent(state, date(2026, 9, 4), "hellybracha@gmail.com"))
            self.assertFalse(already_sent(state, date(2026, 9, 3), "someone@example.com"))
            self.assertEqual(json.loads(path.read_text())["workflow_role"], "primary")


class CliTests(unittest.TestCase):
    def test_resolve_trading_date(self):
        after_close = datetime(2026, 9, 7, 23, 15, tzinfo=ISRAEL_TZ)  # Monday 16:15 New York
        self.assertEqual(cli.resolve_trading_date(None, after_close), date(2026, 9, 7))
        morning = datetime(2026, 9, 8, 10, 0, tzinfo=ISRAEL_TZ)
        self.assertEqual(cli.resolve_trading_date(None, morning), date(2026, 9, 7))
        weekend = datetime(2026, 9, 6, 12, 0, tzinfo=ISRAEL_TZ)  # Sunday
        self.assertEqual(cli.resolve_trading_date(None, weekend), date(2026, 9, 4))
        self.assertEqual(cli.resolve_trading_date("2026-09-02", morning), date(2026, 9, 2))

    def test_offline_dry_run(self):
        with tempfile.TemporaryDirectory() as folder:
            outputs = Path(folder) / "outputs.txt"
            summary = Path(folder) / "summary.md"
            os.environ["GITHUB_OUTPUT"] = str(outputs)
            os.environ["GITHUB_STEP_SUMMARY"] = str(summary)
            try:
                code = cli.main(["--offline", "--dry-run", "--trading-date", "2026-09-03", "--output-dir", folder])
            finally:
                os.environ.pop("GITHUB_OUTPUT", None)
                os.environ.pop("GITHUB_STEP_SUMMARY", None)
            self.assertEqual(code, 0)
            files = sorted(path.name for path in Path(folder).iterdir())
            self.assertIn("narration.txt", files)
            self.assertIn("email.html", files)
            self.assertIn("מבזק בוקר 04.09.2026.docx", files)
            self.assertIn("sent=false", outputs.read_text())
            self.assertIn("trading_date=2026-09-03", outputs.read_text())
            self.assertIn(OPENING, summary.read_text(encoding="utf-8"))

    def test_merge_leader_reason_with_hebrew_name(self):
        data = [
            Paragraph("leader", "מניית Intuitive Machines זינקה אמש בשבעה אחוזים ושתי עשיריות.\nמנגד, מניית X צנחה אמש בכעשרה אחוזים.",
                      data={"leader_name": "Intuitive Machines"}),
            Paragraph("us_close", "טקסט."),
        ]
        news = [
            Paragraph("leader_reason", "זאת לאחר שהחברה הודיעה כי נבחרה לתוכנית לבניית תשתית תקשורת לוויינית.",
                      origin="llm", source_ids=[1], data={"hebrew_name": "חברת תחום החלל אינטואיטיב מאשינס"}),
            Paragraph("macro", "נתון.", origin="llm", source_ids=[1]),
        ]
        merged = cli.merge_paragraphs(data, news)
        self.assertEqual(len(merged), 3)
        self.assertEqual(
            merged[0].lines[0],
            "מניית חברת תחום החלל אינטואיטיב מאשינס (Intuitive Machines) זינקה אמש בשבעה אחוזים ושתי עשיריות. "
            "זאת לאחר שהחברה הודיעה כי נבחרה לתוכנית לבניית תשתית תקשורת לוויינית.",
        )
        self.assertEqual(merged[0].lines[1], "מנגד, מניית X צנחה אמש בכעשרה אחוזים.")


if __name__ == "__main__":
    unittest.main()
