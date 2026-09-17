from __future__ import annotations

import json
import urllib.request
from datetime import date, timedelta

from lawn.models import Day, Yard


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "gress-optmizer/1.0"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.load(resp)


def parse_day(fd: dict) -> Day:
    day = fd["day"]
    return Day(date=fd["date"], tmax=day["maxtemp_c"], tmin=day["mintemp_c"], rain=day["totalprecip_mm"])


def fetch_weather(key: str, yard: Yard, forecast_days: int = 14, history_days: int = 7) -> tuple[dict, list[Day], list[Day]]:
    q = f"{yard.lat},{yard.lon}"
    base = "http://api.weatherapi.com/v1"
    fc = _get(f"{base}/forecast.json?key={key}&q={q}&days={forecast_days}&aqi=no&alerts=no")
    forecast = [parse_day(fd) for fd in fc["forecast"]["forecastday"]]
    today = date.fromisoformat(forecast[0].date)
    history = []
    for back in range(history_days, 0, -1):
        dt = (today - timedelta(days=back)).isoformat()
        raw = _get(f"{base}/history.json?key={key}&q={q}&dt={dt}")
        history.append(parse_day(raw["forecast"]["forecastday"][0]))
    return fc["location"], history, forecast


def fetch_horizon(key: str, yard: Yard, today: date, offsets: tuple[int, ...] = (16, 21, 25, 28, 35, 42)) -> list[Day]:
    q = f"{yard.lat},{yard.lon}"
    extra = []
    for n in offsets:
        dt = (today + timedelta(days=n)).isoformat()
        raw = _get(f"http://api.weatherapi.com/v1/future.json?key={key}&q={q}&dt={dt}")
        extra.append(parse_day(raw["forecast"]["forecastday"][0]))
    return extra
