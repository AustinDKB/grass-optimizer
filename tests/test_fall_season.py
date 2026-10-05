import unittest
from datetime import date, datetime, timedelta

from lawn.models import Day, Yard
from lawn.rules import cut_height, project_schedule, third_floor
from lawn.season import (
    blade_estimate,
    climate_dates,
    dormant_day,
    fall_plan,
    growth_potential,
    hose_cleanup_day,
    ice_degree_hours,
    percentile_md,
    soil_factor,
    synth_hourly,
)


def hours(start: str, temps: list[float]) -> list[tuple[str, float]]:
    t0 = datetime.fromisoformat(start)
    return [((t0 + timedelta(hours=i)).isoformat(timespec="minutes"), t) for i, t in enumerate(temps)]


def days(start: str, n: int, hi: float, lo: float, rain: float = 0.0) -> list[Day]:
    d0 = date.fromisoformat(start)
    return [Day(date=(d0 + timedelta(days=i)).isoformat(), tmax=hi, tmin=lo, rain=rain) for i in range(n)]


class GrowthTests(unittest.TestCase):
    def test_growth_potential_peaks_at_20c(self):
        self.assertAlmostEqual(growth_potential(20), 1.0)
        self.assertAlmostEqual(growth_potential(14.5), 0.6065, places=3)
        self.assertLess(growth_potential(2), 0.01)

    def test_soil_factor_ramps_from_4_to_10c(self):
        self.assertEqual(soil_factor(3), 0.0)
        self.assertAlmostEqual(soil_factor(7), 0.5)
        self.assertEqual(soil_factor(12), 1.0)


class IceTests(unittest.TestCase):
    def test_quarter_inch_needs_about_37_degree_hours(self):
        self.assertAlmostEqual(ice_degree_hours(6.35), 36.8, delta=0.2)

    def test_evening_spell_means_cleanup_that_day(self):
        temps = [5.0] * 6 + [-5.0] * 12  # 12:00-17:00 warm, then -5 from 18:00
        day, hit = hose_cleanup_day(hours("2026-10-11T12:00", temps), 36.8, 0.0)
        self.assertEqual(day, "2026-10-11")
        self.assertEqual(hit, "2026-10-12T01:00")

    def test_early_morning_spell_means_cleanup_the_day_before(self):
        temps = [-5.0] * 10  # from 03:00
        day, _ = hose_cleanup_day(hours("2026-10-12T03:00", temps), 36.8, 0.0)
        self.assertEqual(day, "2026-10-11")

    def test_a_warm_afternoon_melts_it_back(self):
        temps = [-2.0] * 10 + [5.0] * 6 + [-2.0] * 10
        self.assertEqual(hose_cleanup_day(hours("2026-10-11T20:00", temps), 36.8, 0.0), (None, None))

    def test_margin_makes_a_zero_degree_night_count(self):
        temps = [0.0] * 24
        self.assertIsNone(hose_cleanup_day(hours("2026-10-11T18:00", temps), 36.8, 0.0)[0])
        self.assertIsNotNone(hose_cleanup_day(hours("2026-10-11T18:00", temps), 36.8, 2.0)[0])


class DormancyTests(unittest.TestCase):
    def test_needs_the_full_run_of_cold_days(self):
        soil = {f"2026-10-{d:02d}": (3.0 if 10 <= d <= 13 else 8.0) for d in range(5, 20)}
        self.assertIsNone(dormant_day(soil, 5.0, 5))
        soil["2026-10-14"] = 4.0
        self.assertEqual(dormant_day(soil, 5.0, 5), "2026-10-10")


class ClimateTests(unittest.TestCase):
    def test_percentile_counts_years_without_an_event_as_late(self):
        mds = ["10-0%d" % i for i in range(1, 10)] + [None] * 6
        self.assertEqual(percentile_md(mds, 20), "10-03")
        self.assertIsNone(percentile_md([None, None, "10-05"], 50))

    def test_climate_dates_from_past_years(self):
        def year(y, cold_from):
            t0 = f"{y}-09-01T00:00"
            n = 24 * 60
            air = [10.0 if i < cold_from * 24 else -6.0 for i in range(n)]
            soil = [9.0 if i < cold_from * 24 else 2.0 for i in range(n)]
            return {"start": t0, "air": air, "soil": soil}

        clim = {"years": {"2020": year("2020", 40), "2021": year("2021", 45)}}  # Oct 11, Oct 16
        hose, dorm = climate_dates(clim, "2026-10-01", Yard(hose_risk_pct=50))
        self.assertEqual(hose, "2026-10-10")  # cold from 00:00 Oct 11 -> clean up Oct 10
        self.assertEqual(dorm, "2026-10-11")


class SynthTests(unittest.TestCase):
    def test_min_at_six_max_at_fifteen(self):
        h = dict(synth_hourly([Day(date="2026-10-05", tmax=20, tmin=6, rain=0)]))
        self.assertAlmostEqual(h["2026-10-05T06:00"], 6)
        self.assertAlmostEqual(h["2026-10-05T15:00"], 20)


class BladeTests(unittest.TestCase):
    def test_blade_is_last_cut_plus_growth(self):
        y = Yard(mow_log={"2026-10-03": 3.5}, mower_height_inches=3.5, last_mow_date="2026-10-03")
        h, _, implied = blade_estimate(y, "2026-10-06", {"2026-10-04": 0.1, "2026-10-05": 0.1})
        self.assertAlmostEqual(h, 3.7)
        self.assertIsNone(implied)

    def test_measurement_resets_the_estimate_and_implies_a_rate(self):
        y = Yard(
            mow_log={"2026-10-03": 3.5}, mower_height_inches=3.5, last_mow_date="2026-10-03",
            height_log={"2026-10-05": 4.0}, growth_rate_in_day=0.15,
        )
        h, basis, implied = blade_estimate(y, "2026-10-06", {"2026-10-04": 0.1, "2026-10-05": 0.1})
        self.assertAlmostEqual(h, 4.0)
        self.assertIn("measured", basis)
        self.assertAlmostEqual(implied, 0.75)


class OneThirdTests(unittest.TestCase):
    def test_floor_uses_the_blade_not_the_last_deck_setting(self):
        self.assertEqual(third_floor(3.5), 2.5)
        self.assertEqual(third_floor(3.8), 3.0)  # 2.53 -> 3.0

    def test_one_notch_per_cut(self):
        self.assertEqual(cut_height(3.5, 2.5, blade=3.6), 3.0)
        self.assertEqual(cut_height(3.0, 2.5, blade=3.1), 2.5)
        self.assertEqual(cut_height(2.5, 3.5, blade=2.6), 3.5)  # raising is free


class FallPlanTests(unittest.TestCase):
    def test_two_stage_cut_before_growth_stops(self):
        week = days("2026-10-05", 16, hi=16, lo=6)
        s = project_schedule(
            week, 20, 2, "low", {}, Yard(), height=3.5, blade=3.55,
            grow={d.date: 0.03 for d in week}, dormant="2026-10-18",
        )
        heights = [m[1] for m in s.mows]
        self.assertEqual(heights[:2], [3.0, 2.5])
        first, second = (date.fromisoformat(m[0]) for m in s.mows[:2])
        self.assertGreaterEqual((second - first).days, 3)
        self.assertTrue(all(m[0] < "2026-10-18" for m in s.mows))
        self.assertEqual(s.last_mow_of_season, s.mows[-1][0])

    def test_nothing_after_growth_stops_and_no_water_after_cleanup(self):
        week = days("2026-10-05", 10, hi=12, lo=2)
        s = project_schedule(
            week, 5, 6, "low", {}, Yard(), height=3.0, blade=3.1,
            grow={d.date: 0.0 for d in week}, cleanup="2026-10-07", dormant="2026-10-09",
        )
        self.assertTrue(all(w[0] <= "2026-10-07" for w in s.waters))
        self.assertTrue(all(m[0] < "2026-10-09" for m in s.mows))
        final = [w for w in s.waters if w[2] == "final soak"]
        self.assertEqual([w[0] for w in final], ["2026-10-07"])
        self.assertGreater(final[0][1], 2.0)  # fills the soil to capacity (amount depends on ET)

    def test_frost_night_does_not_stop_mowing(self):
        week = days("2026-10-05", 10, hi=18, lo=-2)
        s = project_schedule(week, 20, 12, "low", {}, Yard(), height=3.5, blade=4.0, grow={})
        self.assertLess(s.winter, 3)
        self.assertTrue(s.mows)

    def test_mow_is_never_on_a_water_day(self):
        week = days("2026-10-05", 16, hi=16, lo=6)
        s = project_schedule(
            week, 9, 9, "low", {}, Yard(), height=3.5, blade=3.7,
            grow={d.date: 0.05 for d in week}, cleanup="2026-10-12", dormant="2026-10-20",
        )
        self.assertFalse({m[0] for m in s.mows} & {w[0] for w in s.waters})

    def test_plan_joins_soil_hose_and_grass_stop(self):
        y = Yard(mow_log={"2026-10-03": 3.5}, mower_height_inches=3.5, last_mow_date="2026-10-03")
        rows = []
        t0 = datetime.fromisoformat("2026-09-28T00:00")
        for i in range(24 * 23):
            t = t0 + timedelta(hours=i)
            cold = t >= datetime.fromisoformat("2026-10-09T18:00")
            soil = None if t.date() > date(2026, 10, 12) else (2.0 if cold else 9.0)
            rows.append([t.isoformat(timespec="minutes"), -4.0 if cold else 8.0, soil, 0.0])
        hist = days("2026-09-28", 7, 12, 4)
        fc = days("2026-10-05", 8, 12, 4)
        p = fall_plan(y, "2026-10-05", hist, fc, {"hourly": rows}, None)
        self.assertEqual(p.hose_date, "2026-10-09")
        self.assertEqual(p.dormant_date, "2026-10-10")
        self.assertEqual((p.cleanup_date, p.cleanup_basis), ("2026-10-09", "hose ice"))
        self.assertEqual(p.extra_days[0].date, "2026-10-13")
        self.assertIn("2026-10-10", p.frost_nights)


if __name__ == "__main__":
    unittest.main()
