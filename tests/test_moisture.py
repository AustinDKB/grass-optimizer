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
