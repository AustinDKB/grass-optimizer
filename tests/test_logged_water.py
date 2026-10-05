import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from lawn.daily import merge, record_ledger, replay_start
from lawn.models import Day, Yard
from lawn.rules import Schedule

JEV = {
    "growth": "low",
    "significant_rain_24_48h": 0.0,
    "should_mow_now": 0.0,
    "rain_covers_watering": 0.0,
    "freeze_blowout_now": 0.0,
    "mower_regime": "slowing",
    "model": "test",
}
LOC = {"name": "Martensville", "region": "Saskatchewan"}


def sched(winter=0, water=True):
    return Schedule(
        next_water_date="2026-10-05", next_mow_date=None, last_water_of_season=None,
        last_mow_of_season=None, should_mow=False, should_water=water,
        target_water_mm=9.8, mower_height=3.5, winter=winter, end_balance=0,
    )


class LoggedWaterTests(unittest.TestCase):
    def test_water_logged_today_is_done_not_asked_again(self):
        r = merge(sched(), JEV, 0, LOC, as_of="2026-10-05", watered_today_mm=9.8, recent_water_mm=9.8)
        self.assertFalse(r.lawn_action_items.should_water)
        self.assertFalse(r.lawn_action_items.should_mow)

    def test_merge_uses_the_projection_amount(self):
        s = sched(winter=1)
        s.target_water_mm = 13.56
        r = merge(s, JEV, 12.0, LOC, as_of="2026-10-11")
        self.assertTrue(r.lawn_action_items.should_water)
        self.assertEqual(r.lawn_action_items.target_water_amount_mm, 13.56)


class OncePerDayLedgerTests(unittest.TestCase):
    def test_rerun_same_day_replaces_that_days_row(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.json"
            record_ledger({"ran_at": "a", "as_of": "2026-10-04", "balance_mm": 1}, path)
            record_ledger({"ran_at": "b", "as_of": "2026-10-05", "balance_mm": 2}, path)
            record_ledger({"ran_at": "c", "as_of": "2026-10-05", "balance_mm": 3}, path)
            rows = json.loads(path.read_text())
            self.assertEqual([r["ran_at"] for r in rows], ["c", "a"])


class ReplayStartTests(unittest.TestCase):
    def test_anchors_on_oldest_ledger_day_inside_history(self):
        history = [Day(date=f"2026-10-0{n}", tmax=10, tmin=0, rain=0) for n in range(1, 5)]
        rows = [
            {"as_of": "2026-10-05", "balance_mm": 0},
            {"as_of": "2026-10-03", "balance_mm": 4, "pack_mm": 1},
            {"as_of": "2026-09-20", "balance_mm": 9},
        ]
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.json"
            path.write_text(json.dumps(rows))
            with mock.patch("lawn.daily.LEDGER", path):
                self.assertEqual(replay_start(history, Yard()), (4.0, 1.0, "2026-10-03"))


if __name__ == "__main__":
    unittest.main()
