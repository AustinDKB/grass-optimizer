"""hose_cleaned_on: mark the hose put away so watering and pending cleanup stop."""
import unittest
from datetime import datetime, timedelta

from lawn.models import Day, Yard
from lawn.rules import project_schedule
from lawn.season import fall_plan, hose_cleaned_effective


def days(start: str, n: int, hi: float, lo: float, rain: float = 0.0) -> list[Day]:
    from datetime import date

    d0 = date.fromisoformat(start)
    return [Day(date=(d0 + timedelta(days=i)).isoformat(), tmax=hi, tmin=lo, rain=rain) for i in range(n)]


def cold_hourly(from_iso: str, days_n: int = 20) -> dict:
    """Hourly that forces a hose freeze so fall_plan would otherwise set a pending cleanup."""
    rows = []
    t0 = datetime.fromisoformat(from_iso)
    cold_at = t0 + timedelta(days=4, hours=18)
    for i in range(24 * days_n):
        t = t0 + timedelta(hours=i)
        cold = t >= cold_at
        soil = None if t.date().isoformat() > (t0 + timedelta(days=10)).date().isoformat() else (2.0 if cold else 9.0)
        rows.append([t.isoformat(timespec="minutes"), -4.0 if cold else 8.0, soil, 0.0])
    return {"hourly": rows}


class HoseCleanedEffective(unittest.TestCase):
    def test_unmarked_is_none(self):
        self.assertIsNone(hose_cleaned_effective(Yard(), "2026-10-10"))

    def test_marked_on_or_before_today_counts(self):
        self.assertEqual(hose_cleaned_effective(Yard(hose_cleaned_on="2026-10-08"), "2026-10-10"), "2026-10-08")
        self.assertEqual(hose_cleaned_effective(Yard(hose_cleaned_on="2026-10-10"), "2026-10-10"), "2026-10-10")

    def test_future_date_has_no_effect(self):
        self.assertIsNone(hose_cleaned_effective(Yard(hose_cleaned_on="2026-10-15"), "2026-10-10"))

    def test_last_years_date_is_ignored(self):
        # Same calendar year only: last year's mark must not block spring watering.
        self.assertIsNone(hose_cleaned_effective(Yard(hose_cleaned_on="2025-10-08"), "2026-04-15"))
        self.assertIsNone(hose_cleaned_effective(Yard(hose_cleaned_on="2025-10-08"), "2026-10-10"))


class HoseCleanedFallPlan(unittest.TestCase):
    def test_marked_reports_cleanup_done_not_pending(self):
        y = Yard(hose_cleaned_on="2026-10-04", mow_log={"2026-10-03": 3.5}, mower_height_inches=3.5, last_mow_date="2026-10-03")
        hist = days("2026-09-28", 7, 12, 4)
        fc = days("2026-10-05", 8, 12, 4)
        p = fall_plan(y, "2026-10-05", hist, fc, cold_hourly("2026-09-28T00:00"), None)
        self.assertEqual(p.cleanup_date, "2026-10-04")
        self.assertEqual(p.cleanup_basis, "done")

    def test_unmarked_still_gets_pending_cleanup(self):
        y = Yard(mow_log={"2026-10-03": 3.5}, mower_height_inches=3.5, last_mow_date="2026-10-03")
        hist = days("2026-09-28", 7, 12, 4)
        fc = days("2026-10-05", 8, 12, 4)
        p = fall_plan(y, "2026-10-05", hist, fc, cold_hourly("2026-09-28T00:00"), None)
        self.assertIsNotNone(p.cleanup_date)
        self.assertNotEqual(p.cleanup_basis, "done")

    def test_future_mark_leaves_pending_cleanup(self):
        y = Yard(hose_cleaned_on="2026-10-20", mow_log={"2026-10-03": 3.5}, mower_height_inches=3.5, last_mow_date="2026-10-03")
        hist = days("2026-09-28", 7, 12, 4)
        fc = days("2026-10-05", 8, 12, 4)
        p = fall_plan(y, "2026-10-05", hist, fc, cold_hourly("2026-09-28T00:00"), None)
        self.assertNotEqual(p.cleanup_basis, "done")
        self.assertIsNotNone(p.cleanup_date)

    def test_last_years_mark_leaves_pending_cleanup(self):
        y = Yard(hose_cleaned_on="2025-10-04", mow_log={"2026-10-03": 3.5}, mower_height_inches=3.5, last_mow_date="2026-10-03")
        hist = days("2026-09-28", 7, 12, 4)
        fc = days("2026-10-05", 8, 12, 4)
        p = fall_plan(y, "2026-10-05", hist, fc, cold_hourly("2026-09-28T00:00"), None)
        self.assertNotEqual(p.cleanup_basis, "done")


class HoseCleanedWatering(unittest.TestCase):
    def test_marked_schedules_no_watering(self):
        """Daily run passes cleanup=yesterday when hose is away — no water, no final soak."""
        week = days("2026-10-05", 10, hi=16, lo=6)
        cutoff = "2026-10-04"  # day before run date
        s = project_schedule(
            week, 5, 6, "low", {}, Yard(), height=3.0, blade=3.1,
            grow={d.date: 0.0 for d in week}, cleanup=cutoff,
        )
        self.assertFalse(s.should_water)
        self.assertFalse(s.final_soak_today)
        self.assertEqual(s.waters, [])
        self.assertIsNone(s.next_water_date)
        self.assertIsNone(s.following_water_date)
        self.assertIsNone(s.last_water_of_season)

    def test_unmarked_cleanup_day_still_does_final_soak(self):
        week = days("2026-10-05", 10, hi=12, lo=2)
        s = project_schedule(
            week, 5, 6, "low", {}, Yard(), height=3.0, blade=3.1,
            grow={d.date: 0.0 for d in week}, cleanup="2026-10-07",
        )
        self.assertEqual([w[0] for w in s.waters if w[2] == "final soak"], ["2026-10-07"])


if __name__ == "__main__":
    unittest.main()
