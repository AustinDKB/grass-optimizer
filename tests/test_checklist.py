import unittest

from lawn.checklist import evaluate_checklist
from lawn.models import Day, Yard


def _fc(*pairs):
    out = []
    for i, (hi, lo) in enumerate(pairs):
        out.append(Day(date=f"2026-04-{i+1:02d}", tmax=hi, tmin=lo, rain=0.0))
    return out


class ChecklistTests(unittest.TestCase):
    def test_first_mow_waits_in_s0(self):
        items = {i["id"]: i for i in evaluate_checklist(
            winter=0, spring=0, soil_mm=12, pack_mm=8, forecast=_fc((8, -1), (9, 0)),
            yard=Yard(), days_since_mow=20, should_water=False,
        )}
        self.assertEqual(items["first_mow"]["status"], "wait")

    def test_first_mow_eligible_in_s1_dry_day(self):
        items = {i["id"]: i for i in evaluate_checklist(
            winter=0, spring=1, soil_mm=12, pack_mm=0, forecast=_fc((12, 2), (13, 3)),
            yard=Yard(), days_since_mow=20, should_water=False,
        )}
        self.assertEqual(items["first_mow"]["status"], "eligible")

    def test_first_water_skips_when_soil_wet(self):
        items = {i["id"]: i for i in evaluate_checklist(
            winter=0, spring=1, soil_mm=20, pack_mm=0, forecast=_fc((12, 2), (13, 3)),
            yard=Yard(), days_since_mow=5, should_water=False,
        )}
        self.assertEqual(items["first_water"]["status"], "skip")

    def test_disabled_item_skipped(self):
        y = Yard(checklist_enabled={"overseed": False})
        items = {i["id"]: i for i in evaluate_checklist(
            winter=0, spring=2, soil_mm=12, pack_mm=0, forecast=_fc((16, 4), (17, 5)),
            yard=y, days_since_mow=5, should_water=False,
        )}
        self.assertEqual(items["overseed"]["status"], "skip")


if __name__ == "__main__":
    unittest.main()
