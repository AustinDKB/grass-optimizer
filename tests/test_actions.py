import unittest

from lawn.actions import actions_from_yard, yard_patch_from_actions
from lawn.models import Yard


class ActionsRoundTrip(unittest.TestCase):
    def test_yard_to_sorted_action_rows_includes_full_mow_log(self):
        y = Yard(
            last_mow_date="2026-10-03",
            mower_height_inches=3.5,
            mow_log={"2026-09-17": 3.0, "2026-10-03": 3.5},
            scheduled_water_minutes={"2026-10-04": 60.0, "2026-09-23": 60.0},
        )
        self.assertEqual(
            actions_from_yard(y),
            [
                {"date": "2026-09-17", "action": "mow", "amount": 3.0},
                {"date": "2026-09-23", "action": "water", "amount": 60.0},
                {"date": "2026-10-03", "action": "mow", "amount": 3.5},
                {"date": "2026-10-04", "action": "water", "amount": 60.0},
            ],
        )

    def test_empty_mow_log_shows_no_cuts(self):
        y = Yard(
            last_mow_date="2026-10-03",
            mower_height_inches=3.5,
            mow_log={},
            scheduled_water_minutes={},
        )
        self.assertEqual(actions_from_yard(y), [])

    def test_load_yard_migrates_missing_mow_log(self):
        import json
        import tempfile
        from pathlib import Path
        from unittest import mock

        from lawn import daily

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = Yard(
                last_mow_date="2026-10-03",
                mower_height_inches=3.5,
                scheduled_water_minutes={},
            ).model_dump()
            del raw["mow_log"]
            (root / "yard.json").write_text(json.dumps(raw))
            with mock.patch.object(daily, "ROOT", root):
                yard = daily.load_yard()
            self.assertEqual(yard.mow_log, {"2026-10-03": 3.5})
            saved = json.loads((root / "yard.json").read_text())
            self.assertEqual(saved["mow_log"], {"2026-10-03": 3.5})

    def test_actions_to_yard_keeps_all_waters_and_all_mows(self):
        patch = yard_patch_from_actions(
            [
                {"date": "2026-09-23", "action": "water", "amount": 60},
                {"date": "2026-09-20", "action": "mow", "amount": 3.0},
                {"date": "2026-10-03", "action": "mow", "amount": 3.5},
                {"date": "2026-10-04", "action": "water", "amount": 60},
            ]
        )
        self.assertEqual(
            patch["scheduled_water_minutes"],
            {"2026-09-23": 60.0, "2026-10-04": 60.0},
        )
        self.assertEqual(patch["mow_log"], {"2026-09-20": 3.0, "2026-10-03": 3.5})
        self.assertEqual(patch["last_mow_date"], "2026-10-03")
        self.assertEqual(patch["mower_height_inches"], 3.5)

    def test_no_mow_rows_clears_mow_log_omits_latest_fields(self):
        patch = yard_patch_from_actions(
            [{"date": "2026-10-04", "action": "water", "amount": 60}]
        )
        self.assertEqual(
            patch,
            {
                "scheduled_water_minutes": {"2026-10-04": 60.0},
                "mow_log": {},
                "height_log": {},
            },
        )

    def test_save_yard_merges_actions(self):
        import json
        import tempfile
        from pathlib import Path
        from unittest import mock

        from lawn import daily

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "yard.json").write_text(
                Yard(
                    last_mow_date="2026-09-17",
                    mower_height_inches=3.0,
                    mow_log={"2026-09-17": 3.0},
                    scheduled_water_minutes={"2026-09-18": 50.0},
                ).model_dump_json()
            )
            with mock.patch.object(daily, "ROOT", root), mock.patch.object(daily, "PUBLISH", root / "missing"):
                yard = daily.save_yard(
                    {
                        "actions": [
                            {"date": "2026-09-17", "action": "mow", "amount": 3.0},
                            {"date": "2026-10-03", "action": "mow", "amount": 3.5},
                            {"date": "2026-10-04", "action": "water", "amount": 60},
                        ]
                    }
                )
            saved = json.loads((root / "yard.json").read_text())
            self.assertEqual(yard.last_mow_date, "2026-10-03")
            self.assertEqual(yard.mower_height_inches, 3.5)
            self.assertEqual(saved["mow_log"], {"2026-09-17": 3.0, "2026-10-03": 3.5})
            self.assertEqual(saved["scheduled_water_minutes"], {"2026-10-04": 60.0})


if __name__ == "__main__":
    unittest.main()
