from __future__ import annotations

import json
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

from lawn.models import Day, Yard

BASE = "https://api.openweathermap.org/data/3.0"


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "gress-optmizer/1.0"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.load(resp)


def location_of(yard: Yard, timezone_name: str = "America/Regina") -> dict:
    parts = [p.strip() for p in yard.address.split(",") if p.strip()]
    name = parts[-2] if len(parts) >= 2 else "Martensville"
    region = parts[-1] if parts else "SK"
    if region.upper() in {"SK", "SASK"}:
        region = "Saskatchewan"
    return {
        "name": name,
        "region": region,
        "lat": yard.lat,
        "lon": yard.lon,
        "tz_id": timezone_name,
    }


def _local_date(ts: int, timezone_offset: int) -> str:
    tz = timezone(timedelta(seconds=timezone_offset))
    return datetime.fromtimestamp(ts, tz=tz).date().isoformat()


def parse_onecall_daily(raw: dict, timezone_offset: int) -> Day:
    temp = raw["temp"]
    rain = float(raw.get("rain") or 0) + float(raw.get("snow") or 0)
    return Day(
        date=_local_date(int(raw["dt"]), timezone_offset),
        tmax=float(temp["max"]),
        tmin=float(temp["min"]),
        rain=rain,
    )


def parse_day_summary(raw: dict) -> Day:
    temp = raw["temperature"]
    precip = raw.get("precipitation") or {}
    return Day(
        date=str(raw["date"]),
        tmax=float(temp["max"]),
        tmin=float(temp["min"]),
        rain=float(precip.get("total") or 0),
    )


def _day_summary(key: str, yard: Yard, iso: str) -> Day | None:
    url = (
        f"{BASE}/onecall/day_summary?lat={yard.lat}&lon={yard.lon}"
        f"&date={iso}&appid={key}&units=metric"
    )
    try:
        return parse_day_summary(_get(url))
    except urllib.error.HTTPError:
        return None


def _summaries(key: str, yard: Yard, dates: list[str]) -> list[Day]:
    if not dates:
        return []
    with ThreadPoolExecutor(max_workers=min(8, len(dates))) as pool:
        results = list(pool.map(lambda iso: _day_summary(key, yard, iso), dates))
    return [d for d in results if d is not None]


def fetch_weather(
    key: str, yard: Yard, forecast_days: int = 14, history_days: int = 7
) -> tuple[dict, list[Day], list[Day]]:
    """Forecast from One Call daily (up to 8 days); history from day_summary."""
    oc = _get(
        f"{BASE}/onecall?lat={yard.lat}&lon={yard.lon}&appid={key}"
        f"&units=metric&exclude=minutely,hourly,alerts"
    )
    offset = int(oc.get("timezone_offset") or 0)
    forecast = [parse_onecall_daily(d, offset) for d in oc.get("daily") or []]
    if forecast_days and len(forecast) > forecast_days:
        forecast = forecast[:forecast_days]
    if not forecast:
        raise RuntimeError("OpenWeather One Call returned no daily forecast")
    today = date.fromisoformat(forecast[0].date)
    hist_dates = [(today - timedelta(days=back)).isoformat() for back in range(history_days, 0, -1)]
    history = _summaries(key, yard, hist_dates)
    loc = location_of(yard, oc.get("timezone") or "America/Regina")
    return loc, history, forecast


def fetch_horizon(
    key: str, yard: Yard, today: date, offsets: tuple[int, ...] = (16, 21, 25, 28, 35, 42)
) -> list[Day]:
    """Long-range days via day_summary (OWM supports ~1.5y). Skip failures."""
    return _summaries(key, yard, [(today + timedelta(days=n)).isoformat() for n in offsets])
