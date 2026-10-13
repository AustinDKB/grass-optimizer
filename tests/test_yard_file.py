import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lawn import daily
from lawn.models import Yard

REPO = Path(__file__).resolve().parent.parent


class YardFile(unittest.TestCase):
    def test_load_yard_falls_back_to_example(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "yard.example.json").write_text(
                Yard(address="Example, SK", lat=1.0, lon=2.0).model_dump_json()
            )
            with mock.patch.object(daily, "ROOT", root):
                yard = daily.load_yard()
            self.assertEqual((yard.address, yard.lat, yard.lon), ("Example, SK", 1.0, 2.0))

    def test_yard_json_wins_over_example(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "yard.example.json").write_text(Yard(address="Example, SK").model_dump_json())
            (root / "yard.json").write_text(Yard(address="Private").model_dump_json())
            with mock.patch.object(daily, "ROOT", root):
                self.assertEqual(daily.load_yard().address, "Private")

    def test_save_yard_writes_yard_json_not_example(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            example = Yard(address="Example, SK").model_dump_json()
            (root / "yard.example.json").write_text(example)
            with mock.patch.object(daily, "ROOT", root):
                daily.save_yard({"sqft": 500.0})
            self.assertEqual((root / "yard.example.json").read_text(), example)
            saved = json.loads((root / "yard.json").read_text())
            self.assertEqual((saved["address"], saved["sqft"]), ("Example, SK", 500.0))

    def test_committed_example_is_generic_saskatoon(self):
        raw = json.loads((REPO / "yard.example.json").read_text())
        self.assertEqual((raw["address"], raw["lat"], raw["lon"]), ("Saskatoon, SK", 52.13, -106.67))

    def test_yard_json_is_gitignored(self):
        result = subprocess.run(
            ["git", "check-ignore", "-q", "yard.json"], cwd=REPO, check=False
        )
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
