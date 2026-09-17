from dataclasses import dataclass

from lawn.models import Day

CAPACITY = 25.0
TRIGGER = 10.0
MAJOR_RAIN = 8.0
WINTER_SOAK = 25.0
DECK = (1.25, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0)
INTERVAL = {"low": 10, "medium": 7, "high": 5}
# FAO extra-terrestrial radiation MJ/m2/day at 50N; Martensville is 52.3N.
RA_MJ = (6.1, 10.2, 16.5, 23.6, 29.2, 31.4, 30.5, 25.4, 18.1, 11.6, 6.9, 4.9)


def irrigation_mm(gpm: float, minutes: float, sqft: float) -> float:
    return (gpm * minutes * 3.785411784) / (sqft * 0.09290304)


CYCLE_MM = round(irrigation_mm(4, 50, 1000), 2)


def snap_deck(inches: float) -> float:
    return min(DECK, key=lambda notch: (abs(notch - inches), -notch))


# Summer 3.5, slowing 2.75→3.0, final 2.0–2.5→2.5. Deck has no 2.75 or 2.25.
HEIGHT = tuple(snap_deck(h) for h in (3.5, 2.75, 2.25, 2.25))


def step_balance(prev: float, rain: float, manual: float, et: float, capacity: float = CAPACITY) -> float:
    return min(capacity, max(0.0, prev + rain + manual - et))


def et_mm(tmax: float, tmin: float, month: int, kc: float = 0.85) -> float:
    ra_mm = RA_MJ[month - 1] * 0.408
    tmean = (tmax + tmin) / 2
    spread = max(tmax - tmin, 0.1) ** 0.5
    # ponytail: 1.25 prairie-arid factor; FAO-56 if we ever get WeatherAPI et0.
    return max(0.0, 0.0023 * ra_mm * (tmean + 17.8) * spread * kc * 1.25)


def consistently_below(vals: list[float], cap: float) -> bool:
    if not vals:
        return False
    need = max(1, -(-len(vals) * 7 // 10))
    return sum(v < cap for v in vals) >= need


def winter_status(highs: list[float], lows: list[float]) -> int:
    if any(t <= 0 for t in lows):
        return 3
    if consistently_below(highs, 8):
        return 2
    if consistently_below(highs, 15):
        return 1
    return 0


def decide_mow(
    days_since: int,
    growth: str,
    rain_24_48: float,
    watering_today: bool,
    winter: int = 0,
) -> bool:
    if days_since <= 0:
        return False
    interval = INTERVAL[growth]
    close = days_since >= max(interval - 2, 3)
    if close and rain_24_48 >= MAJOR_RAIN:
        return True
    if close and watering_today:
        return True
    if close and winter >= 1:
        return True
    if winter >= 2:
        return True
    return days_since >= interval


def rain_soon(days: list[Day], i: int) -> float:
    return sum(d.rain for d in days[i + 1 : i + 3])


def water_mm(balance: float, scheduled: float, winter: int, coming: float, soaked: bool) -> tuple[float, bool]:
    if scheduled:
        return scheduled, True
    if winter >= 3 and not soaked:
        return WINTER_SOAK, True
    if coming >= MAJOR_RAIN:
        return 0.0, False
    if balance < TRIGGER:
        return CYCLE_MM, True
    return 0.0, False


@dataclass
class Schedule:
    next_water_date: str | None
    next_mow_date: str | None
    last_water_of_season: str | None
    last_mow_of_season: str | None
    should_mow: bool
    should_water: bool
    target_water_mm: float
    mower_height: float
    winter: int
    end_balance: float
    following_water_date: str | None = None
    frost_watch_date: str | None = None


def replay(days: list[Day], start: float = 15.0, manuals: dict[str, float] | None = None) -> float:
    bal, manuals = start, manuals or {}
    for d in days:
        bal = step_balance(bal, d.rain, manuals.get(d.date, 0.0), et_mm(d.tmax, d.tmin, d.month))
    return bal


def note(out: Schedule, when: str, watering: bool, mow: bool, winter: int) -> None:
    if watering and out.next_water_date is None:
        out.next_water_date = when
    elif watering and out.following_water_date is None:
        out.following_water_date = when
    if mow:
        out.next_mow_date = out.next_mow_date or when
    if winter >= 3:
        out.last_water_of_season = out.last_water_of_season or when
    if winter >= 2:
        out.last_mow_of_season = out.last_mow_of_season or when


def season_end(days: list[Day]) -> tuple[str | None, str | None]:
    last_mow = last_water = None
    for d in days:
        if last_mow is None and d.tmax < 8:
            last_mow = d.date
        if d.tmin <= 0:
            return last_mow or d.date, d.date
    return last_mow, last_water


def project_schedule(
    days: list[Day],
    start_balance: float,
    days_since_mow: int,
    growth: str,
    scheduled_water: dict[str, float],
) -> Schedule:
    out = Schedule(None, None, None, None, False, False, 0.0, 3.5, 0, start_balance)
    balance, since = start_balance, days_since_mow
    for i, day in enumerate(days):
        slice7 = days[i : i + 7]
        winter = winter_status([d.tmax for d in slice7], [d.tmin for d in slice7])
        coming = rain_soon(days, i)
        soaked = out.last_water_of_season is not None
        manual, watering = water_mm(balance, scheduled_water.get(day.date, 0.0), winter, coming, soaked)
        mow = decide_mow(since, growth, coming, watering, winter)
        note(out, day.date, watering, mow, winter)
        if i == 0:
            out.should_mow = mow
            out.should_water = watering
            out.target_water_mm = manual if watering else 0.0
            out.mower_height = HEIGHT[winter]
            out.winter = winter
        balance = step_balance(balance, day.rain, manual, et_mm(day.tmax, day.tmin, day.month))
        since = 0 if mow else since + 1
    out.end_balance = balance
    return out
