import unittest

from lawn.models import Day, Yard
from lawn.rules import growth_from_highs, season_height, spring_heights, spring_status, winter_status


class GrowthTests(unittest.TestCase):
    def test_bands(self):
        self.assertEqual(growth_from_highs([12, 13, 14, 12, 11, 10, 12]), "low")
        self.assertEqual(growth_from_highs([18, 19, 20, 17, 16, 18, 19]), "medium")
        self.assertEqual(growth_from_highs([24, 25, 26, 23, 22, 24, 25]), "high")
        self.assertEqual(growth_from_highs([]), "low")


class SpringStatusTests(unittest.TestCase):
    def test_s0_when_pack_or_freeze(self):
        highs = [12, 12, 12, 12, 12, 12, 12]
        lows = [2, 2, 2, 2, 2, 2, 2]
        self.assertEqual(spring_status(highs, lows, pack_mm=10, yard=Yard()), 0)
        self.assertEqual(spring_status(highs, [-1, 2, 2, 2, 2, 2, 2], pack_mm=0, yard=Yard()), 0)

    def test_s1_green_up(self):
        highs = [11, 12, 13, 11, 12, 10, 11]
        lows = [1, 2, 1, 2, 1, 2, 1]
        self.assertEqual(spring_status(highs, lows, pack_mm=0, yard=Yard()), 1)

    def test_s2_when_highs_mostly_15(self):
        highs = [16, 17, 15, 16, 18, 15, 16]
        lows = [4, 5, 4, 5, 4, 5, 4]
        self.assertEqual(spring_status(highs, lows, pack_mm=0, yard=Yard()), 2)


class SeasonHeightTests(unittest.TestCase):
    def test_winter_lockdown_wins(self):
        y = Yard()
        self.assertEqual(season_height(winter=3, spring=2, yard=y), 2.5)

    def test_spring_raises_toward_summer(self):
        y = Yard()
        self.assertEqual(season_height(winter=0, spring=1, yard=y), spring_heights(y)[1])
        self.assertEqual(season_height(winter=0, spring=2, yard=y), spring_heights(y)[2])


if __name__ == "__main__":
    unittest.main()
