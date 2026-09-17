import math
from dataclasses import dataclass
from datetime import date

from lawn.models import Day, Yard

GSC = 0.0820
CAPACITY = 25.0
TRIGGER = 10.0
MAJOR_RAIN = 8.0
WINTER_SOAK = 25.0
DECK = (1.25, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0)
INTERVAL = {"low": 10, "medium": 7, "high": 5}


def irrigation_mm(gpm: float, minutes: float, sqft: float) -> float:
    return (gpm * minutes * 3.785411784) / (sqft * 0.09290304)


def cycle_mm(yard: Yard | None = None) -> float:
    y = yard or Yard()
    return round(irrigation_mm(y.gpm, y.cycle_minutes, y.sqft), 2)


CYCLE_MM = cycle_mm()


def manuals_mm(yard: Yard | None = None) -> dict[str, float]:
    y = yard or Yard()
    return {d: round(irrigation_mm(y.gpm, m, y.sqft), 2) for d, m in y.scheduled_water_minutes.items()}


def days_since_mow(today: date, last: str) -> int:
    return max(0, (today - date.fromisoformat(last)).days)


def snap_deck(inches: float, deck: list[float] | tuple[float, ...] | None = None) -> float:
    notches = tuple(deck) if deck is not None else DECK
    return min(notches, key=lambda notch: (abs(notch - inches), -notch))


def heights(yard: Yard | None = None) -> tuple[float, ...]:
    y = yard or Yard()
    return tuple(snap_deck(h, y.mower_deck) for h in y.height_targets_in)


HEIGHT = heights()


def ra_mj(lat: float, iso: str) -> float:
    y, m, d = (int(p) for p in iso.split("-"))
    j = date(y, m, d).timetuple().tm_yday
    phi = math.radians(lat)
    dr = 1 + 0.033 * math.cos(2 * math.pi * j / 365)
    decl = 0.409 * math.sin(2 * math.pi * j / 365 - 1.39)
    ws = math.acos(max(-1.0, min(1.0, -math.tan(phi) * math.tan(decl))))
    return (24 * 60 / math.pi) * GSC * dr * (
        ws * math.sin(phi) * math.sin(decl) + math.cos(phi) * math.cos(decl) * math.sin(ws)
    )


def et_mm(tmax: float, tmin: float, iso: str, yard: Yard | None = None) -> float:
    y = yard or Yard()
    ra_mm = ra_mj(y.lat, iso) * 0.408
    tmean = (tmax + tmin) / 2
    spread = max(tmax - tmin, 0.1) ** 0.5
    return max(0.0, 0.0023 * ra_mm * (tmean + 17.8) * spread * y.kc * y.et_factor)


def step_balance(prev: float, rain: float, manual: float, et: float, capacity: float = CAPACITY) -> float:
    return min(capacity, max(0.0, prev + rain + manual - et))


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
    interval: dict[str, int] | None = None,
    major_rain: float = MAJOR_RAIN,
) -> bool:
    if days_since <= 0:
        return False
    gap = (interval or INTERVAL)[growth]
    close = days_since >= max(gap - 2, 3)
    if close and rain_24_48 >= major_rain:
        return True
    if close and watering_today:
        return True
    if close and winter >= 1:
        return True
    if winter >= 2:
        return True
    return days_since >= gap


def rain_soon(days: list[Day], i: int) -> float:
    return sum(d.rain for d in days[i + 1 : i + 3])


def water_mm(
    balance: float,
    scheduled: float,
    winter: int,
    coming: float,
    soaked: bool,
    yard: Yard | None = None,
) -> tuple[float, bool]:
    y = yard or Yard()
    if scheduled:
        return scheduled, True
    if winter >= 3 and not soaked:
        return y.winter_soak_mm, True
    if coming >= y.major_rain_mm:
        return 0.0, False
    if balance < y.trigger_mm:
        return cycle_mm(y), True
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


def replay(
    days: list[Day],
    start: float = 15.0,
    manuals: dict[str, float] | None = None,
    yard: Yard | None = None,
    since: str | None = None,
) -> float:
    y, manuals = yard or Yard(), manuals or {}
    bal = start
    for d in days:
        if since is not None and d.date < since:
            continue
        et = et_mm(d.tmax, d.tmin, d.date, y)
        bal = step_balance(bal, d.rain, manuals.get(d.date, 0.0), et, y.capacity_mm)
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
    yard: Yard | None = None,
) -> Schedule:
    y = yard or Yard()
    hs = heights(y)
    out = Schedule(None, None, None, None, False, False, 0.0, hs[0], 0, start_balance)
    balance, since = start_balance, days_since_mow
    for i, day in enumerate(days):
        slice7 = days[i : i + 7]
        winter = winter_status([d.tmax for d in slice7], [d.tmin for d in slice7])
        coming = rain_soon(days, i)
        soaked = out.last_water_of_season is not None
        manual, watering = water_mm(
            balance, scheduled_water.get(day.date, 0.0), winter, coming, soaked, y
        )
        mow = decide_mow(since, growth, coming, watering, winter, y.mow_interval_days, y.major_rain_mm)
        note(out, day.date, watering, mow, winter)
        if i == 0:
            out.should_mow = mow
            out.should_water = watering
            out.target_water_mm = manual if watering else 0.0
            out.mower_height = hs[winter]
            out.winter = winter
        et = et_mm(day.tmax, day.tmin, day.date, y)
        balance = step_balance(balance, day.rain, manual, et, y.capacity_mm)
        since = 0 if mow else since + 1
    out.end_balance = balance
    return out
