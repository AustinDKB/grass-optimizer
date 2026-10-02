import unittest
from datetime import date
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError

from lawn.models import Yard
from lawn.weather import (
    fetch_horizon,
    location_of,
    parse_day_summary,
    parse_onecall_daily,
)


class ParseOneCallTests(unittest.TestCase):
    def test_maps_daily_temp_and_precip(self):
        raw = {
            "dt": 1790953200,  # 2026-10-02 local noon-ish America/Regina
            "temp": {"min": 0.81, "max": 13.68},
            "rain": 2.4,
            "snow": 1.1,
        }
        day = parse_onecall_daily(raw, timezone_offset=-21600)
        self.assertEqual(day.date, "2026-10-02")
        self.assertEqual(day.tmax, 13.68)
        self.assertEqual(day.tmin, 0.81)
        self.assertEqual(day.rain, 3.5)

    def test_missing_precip_is_zero(self):
        raw = {"dt": 1790953200, "temp": {"min": 1.0, "max": 10.0}}
        day = parse_onecall_daily(raw, timezone_offset=-21600)
        self.assertEqual(day.rain, 0.0)


class ParseDaySummaryTests(unittest.TestCase):
    def test_maps_summary_temp_and_precip(self):
        raw = {
            "date": "2026-10-01",
            "temperature": {"min": -2.08, "max": 15.92},
            "precipitation": {"total": 0.0},
        }
        day = parse_day_summary(raw)
        self.assertEqual(day.date, "2026-10-01")
        self.assertEqual(day.tmax, 15.92)
        self.assertEqual(day.tmin, -2.08)
        self.assertEqual(day.rain, 0.0)


class LocationTests(unittest.TestCase):
    def test_parses_city_from_yard_address(self):
        loc = location_of(Yard(), "America/Regina")
        self.assertEqual(loc["name"], "Martensville")
        self.assertEqual(loc["region"], "Saskatchewan")
        self.assertEqual(loc["lat"], 52.2897)
        self.assertEqual(loc["tz_id"], "America/Regina")


class HorizonTests(unittest.TestCase):
    def test_skips_blocked_day_summary(self):
        err = HTTPError(
            "https://api.openweathermap.org/data/3.0/onecall/day_summary",
            401,
            "Unauthorized",
            hdrs=None,
            fp=BytesIO(b'{"cod":401}'),
        )
        with patch("lawn.weather._get", side_effect=err):
            days = fetch_horizon("fake-key", Yard(), date(2026, 10, 2), offsets=(16,))
        self.assertEqual(days, [])


if __name__ == "__main__":
    unittest.main()
