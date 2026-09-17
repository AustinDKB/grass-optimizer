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


class RadiationTests(unittest.TestCase):
    def test_ra_matches_fao56_bangkok_15_april(self):
        from lawn.rules import ra_mj
        # FAO-56 Example 8: 13°44'N, 15 April → Ra ≈ 38.1 MJ m-2 d-1
        self.assertAlmostEqual(ra_mj(13.73, "2015-04-15"), 38.1, delta=0.4)

    def test_ra_june_15_at_50n_matches_fao_table(self):
        from lawn.rules import ra_mj
        # FAO-56 Table 2.6 / Eq. 21: ~41.2 MJ m-2 d-1 at 50°N on 15 June
        self.assertAlmostEqual(ra_mj(50.0, "2026-06-15"), 41.2, delta=0.6)


class EtTests(unittest.TestCase):
    def test_june_et_is_higher_at_40n_than_at_martensville(self):
        from lawn.models import Yard
        from lawn.rules import et_mm
        south = et_mm(26, 12, "2026-06-15", Yard(lat=40.0, kc=1.0, et_factor=1.0))
        north = et_mm(26, 12, "2026-06-15", Yard(lat=52.2897, kc=1.0, et_factor=1.0))
        self.assertGreater(south, north)

    def test_et_is_zero_in_deep_cold(self):
        from lawn.rules import et_mm
        self.assertEqual(et_mm(-30, -40, "2026-01-15"), 0.0)


class ConfigTests(unittest.TestCase):
    def test_halving_cycle_minutes_halves_applied_water(self):
        from lawn.models import Yard
        from lawn.rules import cycle_mm
        self.assertAlmostEqual(cycle_mm(Yard(cycle_minutes=50)), 8.15, places=2)
        self.assertAlmostEqual(cycle_mm(Yard(cycle_minutes=25)), 4.07, places=2)

    def test_days_since_mow_counts_from_config_date(self):
        from lawn.rules import days_since_mow
        self.assertEqual(days_since_mow(date(2026, 9, 17), "2026-09-17"), 0)
        self.assertEqual(days_since_mow(date(2026, 9, 24), "2026-09-17"), 7)

    def test_scheduled_water_is_only_the_configured_dates(self):
        from lawn.models import Yard
        from lawn.rules import manuals_mm
        y = Yard(scheduled_water_minutes={"2026-09-18": 50})
        self.assertAlmostEqual(manuals_mm(y)["2026-09-18"], 8.15, places=2)
        self.assertEqual(manuals_mm(Yard(scheduled_water_minutes={})), {})

    def test_replay_applies_only_days_on_or_after_saved_as_of(self):
        from lawn.rules import replay
        days = _days(date(2026, 9, 15), highs=[18, 18, 18], lows=[8, 8, 8], rain=[0, 5, 0])
        full = replay(days, start=15)
        later = replay(days, start=15, since="2026-09-16")
        self.assertGreater(later, full)


class MergeTests(unittest.TestCase):
    def test_lockdown_height_is_a_real_deck_notch(self):
        from lawn.daily import merge
        from lawn.rules import Schedule
        sched = Schedule(
            next_water_date="2026-09-17",
            next_mow_date="2026-09-17",
            last_water_of_season="2026-09-17",
            last_mow_of_season="2026-09-17",
            should_mow=True,
            should_water=True,
            target_water_mm=25,
            mower_height=2.5,
            winter=3,
            end_balance=20,
        )
        jev = {
            "growth": "low",
            "significant_rain_24_48h": 0.0,
            "should_mow_now": 0.0,
            "rain_covers_watering": 0.0,
            "freeze_blowout_now": 1.0,
            "mower_regime": "final",
            "model": "test",
        }
        report = merge(sched, jev, 10, {"name": "Warman", "region": "Saskatchewan"})
        self.assertEqual(report.lawn_action_items.recommended_mower_height_inches, 2.5)
        self.assertEqual(report.feed["cycle_minutes"], 50)
        self.assertEqual(report.feed["gpm"], 4)


if __name__ == "__main__":
    unittest.main()
