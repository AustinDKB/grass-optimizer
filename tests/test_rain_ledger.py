import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from lawn.daily import rain_by_day, record_rain
from lawn.models import Day


class RainLedgerTest(unittest.TestCase):
    def test_past_days_final_and_today_so_far(self):
        history = [Day(date="2026-10-07", tmax=10, tmin=1, rain=0.71)]
        om = {"hourly": [
            ["2026-10-08T06:00", 5, 6, 0.2],
            ["2026-10-08T07:00", 5, 6, 0.3],
            ["2026-10-08T08:00", 5, 6, 9.0],  # not yet happened at 07:00
        ]}
        rain = rain_by_day(history, om, "2026-10-08", "2026-10-08T07:00-06:00")
        self.assertEqual(rain, {"2026-10-07": (0.71, True), "2026-10-08": (0.5, False)})

    def test_partial_count_never_replaces_final(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.json"
            path.write_text(json.dumps([
                {"as_of": "2026-10-08"},
                {"as_of": "2026-10-07", "rain_mm": 4.0, "rain_final": True},
            ]))
            rows = record_rain({"2026-10-08": (0.5, False), "2026-10-07": (1.0, False)}, path)
            self.assertEqual((rows[0]["rain_mm"], rows[0]["rain_final"]), (0.5, False))
            self.assertEqual(rows[1]["rain_mm"], 4.0)


if __name__ == "__main__":
    unittest.main()
