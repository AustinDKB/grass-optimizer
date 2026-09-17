import unittest
from datetime import date

from lawn.rules import (
    Day,
    decide_mow,
    irrigation_mm,
    project_schedule,
    season_end,
    snap_deck,
    step_balance,
    winter_status,
)


class DeckTests(unittest.TestCase):
    def test_snaps_winter_targets_to_real_notches(self):
        self.assertEqual(snap_deck(2.75), 3.0)
        self.assertEqual(snap_deck(2.25), 2.5)
        self.assertEqual(snap_deck(3.0), 3.0)
        self.assertEqual(snap_deck(3.5), 3.5)

    def test_phase_heights_are_real_notches(self):
        from lawn.rules import HEIGHT
        self.assertEqual(HEIGHT, (3.5, 3.0, 2.5, 2.5))


class IrrigationTests(unittest.TestCase):
    def test_50min_4gpm_on_1000sqft_is_about_8mm(self):
        mm = irrigation_mm(gpm=4, minutes=50, sqft=1000)
        self.assertAlmostEqual(mm, 8.15, places=2)


class BalanceTests(unittest.TestCase):
    def test_adds_rain_and_manual_then_subtracts_et(self):
        self.assertEqual(step_balance(10, rain=3, manual=2, et=4), 11)

    def test_clamps_to_capacity_and_zero(self):
        self.assertEqual(step_balance(24, rain=10, manual=0, et=0, capacity=25), 25)
        self.assertEqual(step_balance(1, rain=0, manual=0, et=5), 0)


class MowTests(unittest.TestCase):
    def test_pre_rain_triggers_mow_when_approaching_window(self):
        self.assertTrue(
            decide_mow(days_since=5, growth="medium", rain_24_48=12, watering_today=False)
        )

    def test_no_mow_the_day_after_a_cut(self):
        self.assertFalse(
            decide_mow(days_since=0, growth="high", rain_24_48=20, watering_today=True)
        )

    def test_mow_before_watering_when_window_is_close(self):
        self.assertTrue(
            decide_mow(days_since=5, growth="medium", rain_24_48=0, watering_today=True)
        )


class WinterTests(unittest.TestCase):
    def test_phase1_when_highs_stay_below_15(self):
        highs = [14, 13, 12, 14, 13, 11, 14]
        lows = [6, 5, 4, 6, 5, 3, 6]
        self.assertEqual(winter_status(highs, lows), 1)

    def test_phase2_when_highs_stay_below_8(self):
        highs = [7, 6, 5, 7, 6, 4, 7]
        lows = [2, 1, 1, 2, 1, 0.5, 2]
        self.assertEqual(winter_status(highs, lows), 2)

    def test_lockdown_when_a_night_hits_freezing(self):
        highs = [12, 10, 9, 8, 7, 6, 5]
        lows = [4, 3, 2, 1, 0, -2, -4]
        self.assertEqual(winter_status(highs, lows), 3)


def _days(start: date, highs, lows, rain):
    out = []
    for i, (hi, lo, mm) in enumerate(zip(highs, lows, rain)):
        d = start.replace(day=start.day) if i == 0 else date.fromordinal(start.toordinal() + i)
        out.append(Day(date=d.isoformat(), tmax=hi, tmin=lo, rain=mm))
    return out


class ScheduleTests(unittest.TestCase):
    def test_next_water_is_first_day_balance_falls_below_trigger(self):
        days = _days(
            date(2026, 9, 17),
            highs=[18, 20, 22, 24, 26, 28, 22, 20, 26, 28, 30, 28],
            lows=[10, 12, 12, 14, 15, 16, 10, 10, 14, 16, 16, 14],
            rain=[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        )
        sched = project_schedule(
            days,
            start_balance=20,
            days_since_mow=0,
            growth="medium",
            scheduled_water={"2026-09-18": 8.15},
        )
        self.assertEqual(sched.next_water_date, "2026-09-18")
        self.assertEqual(sched.next_mow_date, "2026-09-24")
        self.assertIsNotNone(sched.following_water_date)
        self.assertGreater(sched.following_water_date, "2026-09-18")

    def test_last_water_and_mow_follow_winter_steps(self):
        days = _days(
            date(2026, 9, 17),
            highs=[14, 13, 12, 10, 8, 7, 6],
            lows=[6, 5, 4, 2, 1, 0, -3],
            rain=[0, 0, 0, 0, 0, 0, 0],
        )
        sched = project_schedule(
            days,
            start_balance=18,
            days_since_mow=8,
            growth="low",
            scheduled_water={},
        )
        # Freeze appears in the 7-day outlook, so soak and final cut happen now.
        self.assertEqual(sched.last_mow_of_season, "2026-09-17")
        self.assertEqual(sched.last_water_of_season, "2026-09-17")
        self.assertTrue(sched.should_mow)
        self.assertTrue(sched.should_water)


class HorizonTests(unittest.TestCase):
    def test_season_end_is_first_sub8_high_and_first_freeze(self):
        days = _days(
            date(2026, 10, 18),
            highs=[11.1, 7.7, 7.1],
            lows=[1.9, -0.3, -0.5],
            rain=[0, 0, 0],
        )
        self.assertEqual(season_end(days), ("2026-10-19", "2026-10-19"))


if __name__ == "__main__":
    unittest.main()
