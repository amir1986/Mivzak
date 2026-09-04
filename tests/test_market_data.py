import unittest
from datetime import date, datetime, time as datetime_time

from mivzak import market_data as md
from mivzak.config import NEW_YORK_TZ


class HelperTests(unittest.TestCase):
    def test_clean_company_name(self):
        self.assertEqual(md.clean_company_name("Astera Labs, Inc."), "Astera Labs")
        self.assertEqual(md.clean_company_name("Cerebras Systems Inc."), "Cerebras Systems")
        self.assertEqual(md.clean_company_name("Broadcom Inc."), "Broadcom")
        self.assertEqual(md.clean_company_name("Snowflake Inc. Class A"), "Snowflake")
        self.assertEqual(md.clean_company_name("Lululemon Athletica Inc."), "Lululemon Athletica")

    def test_quote_from_yahoo_verifies_date(self):
        trading_date = date(2026, 9, 3)
        stamp = int(datetime.combine(trading_date, datetime_time(16, 0), tzinfo=NEW_YORK_TZ).timestamp())
        item = {
            "regularMarketPrice": 7747.71,
            "regularMarketPreviousClose": 7711.30,
            "regularMarketChangePercent": 0.4722,
            "regularMarketTime": stamp,
            "exchangeTimezoneName": "America/New_York",
        }
        quote = md.quote_from_yahoo("^GSPC", item, trading_date)
        self.assertTrue(quote.verified)
        self.assertEqual(quote.kind, "us_index")
        stale = md.quote_from_yahoo("^GSPC", item, date(2026, 9, 4))
        self.assertFalse(stale.verified)

    def test_parse_movers_table(self):
        page = """
        <table><tr><th>Symbol</th></tr>
        <tr><td><a href="/quote/AEHR/">AEHR</a></td><td>Aehr Test Systems, Inc.</td><td></td>
        <td>84.40  +8.13 (+10.66%)</td><td>+8.13</td><td>+10.66%</td><td>1.907M</td></tr>
        <tr><td><a href="/quote/ALAB/">ALAB</a></td><td>Astera Labs, Inc.</td><td></td>
        <td>311.03  +28.21 (+9.97%)</td><td>+28.21</td><td>+9.97%</td><td>2.54M</td></tr>
        </table>
        """
        rows = md.parse_movers_table(page)
        self.assertEqual([row["symbol"] for row in rows], ["AEHR", "ALAB"])
        self.assertAlmostEqual(rows[0]["change_percent"], 10.66)
        self.assertAlmostEqual(rows[0]["price"], 84.40)

    def test_fixture_snapshot(self):
        snapshot = md.fixture_snapshot(date(2026, 9, 3))
        self.assertEqual(snapshot.leader.symbol, "SNOW")
        self.assertEqual(len(snapshot.sectors()), 11)
        self.assertEqual(len(snapshot.by_kind("us_index")), 3)
        self.assertIsNotNone(snapshot.quote("^TNX"))


if __name__ == "__main__":
    unittest.main()
