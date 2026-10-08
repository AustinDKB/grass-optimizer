import unittest

from lawn.models import Day, Yard
from lawn.rules import melt_cap, replay_moisture, step_moisture


def _day(iso: str, tmax: float, tmin: float, rain: float) -> Day:
    return Day(date=iso, tmax=tmax, tmin=tmin, rain=rain)


class MeltCapTests(unittest.TestCase):
    def test_melt_scales_with_tmax_and_yard_factor(self):
        y = Yard(melt_factor_mm_per_c=2.0)
        self.assertEqual(melt_cap(5.0, y), 10.0)
        self.assertEqual(melt_cap(-1.0, y), 0.0)


class StepMoistureTests(unittest.TestCase):
    def test_freezing_day_precip_goes_to_pack_not_soil(self):
        y = Yard(capacity_mm=25)
        soil, pack = step_moisture(5.0, 0.0, _day("2026-01-10", tmax=-2, tmin=-10, rain=4.0), 0.0, y)
        self.assertEqual(soil, 5.0)
        self.assertEqual(pack, 4.0)

    def test_warm_day_melts_pack_into_soil_capped(self):
        y = Yard(capacity_mm=25, melt_factor_mm_per_c=2.0)
        # pack 20, tmax 5 → melt 10; rain 1; start soil 10 → 21 then ET
        soil, pack = step_moisture(10.0, 20.0, _day("2026-03-20", tmax=5, tmin=-1, rain=1.0), 0.0, y)
        self.assertEqual(pack, 10.0)
        self.assertGreater(soil, 10.0)
        self.assertLessEqual(soil, 25.0)

    def test_irrigation_always_hits_soil_even_when_freezing(self):
        y = Yard(capacity_mm=25)
        soil, pack = step_moisture(0.0, 0.0, _day("2026-01-10", tmax=-5, tmin=-12, rain=2.0), 8.0, y)
        self.assertEqual(pack, 2.0)
        self.assertEqual(soil, 8.0)


    def test_only_part_of_the_melt_soaks_in(self):
        y = Yard(capacity_mm=25, melt_factor_mm_per_c=2.0, melt_soak_fraction=0.4, kc=0.0)
        # pack 20, tmax 5 → melt 10, 4 soaks in, 6 runs off; soil not frozen so rain 1 counts fully; no ET
        soil, pack = step_moisture(10.0, 20.0, _day("2026-03-20", tmax=5, tmin=-1, rain=1.0), 0.0, y, frozen=False)
        self.assertEqual(pack, 10.0)
        self.assertAlmostEqual(soil, 15.0)

    def test_rain_on_frozen_ground_soaks_in_like_melt(self):
        y = Yard(capacity_mm=25, melt_soak_fraction=0.4, kc=0.0)
        day = _day("2026-04-05", tmax=6, tmin=-3, rain=10.0)
        self.assertAlmostEqual(step_moisture(10.0, 0.0, day, 0.0, y, frozen=True)[0], 14.0)
        self.assertAlmostEqual(step_moisture(10.0, 0.0, day, 0.0, y, frozen=False)[0], 20.0)

    def test_snow_on_ground_means_frozen_when_soil_temp_unknown(self):
        y = Yard(capacity_mm=25, melt_factor_mm_per_c=2.0, melt_soak_fraction=0.4, kc=0.0)
        # pack 20, tmax 5 → melt 10 → 4; rain 10 on snow → 4; soil 10 → 18
        soil, _ = step_moisture(10.0, 20.0, _day("2026-03-20", tmax=5, tmin=-1, rain=10.0), 0.0, y)
        self.assertAlmostEqual(soil, 18.0)
        # no snow, no soil reading → rain counts fully
        soil, _ = step_moisture(10.0, 0.0, _day("2026-05-20", tmax=5, tmin=-1, rain=10.0), 0.0, y)
        self.assertAlmostEqual(soil, 20.0)

    def test_replay_uses_frozen_days(self):
        y = Yard(capacity_mm=25, melt_soak_fraction=0.4, kc=0.0)
        days = [_day("2026-04-01", 5, -2, 10.0), _day("2026-04-02", 8, 0, 10.0)]
        soil, _ = replay_moisture(days, start_soil=0.0, yard=y, frozen={"2026-04-01": True, "2026-04-02": False})
        self.assertAlmostEqual(soil, 14.0)


class ReplayMoistureTests(unittest.TestCase):
    def test_replay_builds_pack_then_melts(self):
        y = Yard(capacity_mm=25, melt_factor_mm_per_c=2.0)
        days = [
            _day("2026-01-01", -5, -12, 5),
            _day("2026-01-02", -3, -10, 3),
            _day("2026-01-03", 4, -2, 0),
        ]
        soil, pack = replay_moisture(days, start_soil=5.0, start_pack=0.0, manuals={}, yard=y)
        self.assertEqual(pack, 0.0)  # 8 pack melted at 2*4=8
        self.assertGreaterEqual(soil, 5.0)


if __name__ == "__main__":
    unittest.main()
