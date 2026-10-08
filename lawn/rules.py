import math
from dataclasses import dataclass, field
from datetime import date, timedelta

from lawn.models import Day, Yard

GSC = 0.0820
CAPACITY = 25.0
TRIGGER = 10.0
MAJOR_RAIN = 8.0
DECK = (1.25, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0)
INTERVAL = {"low": 10, "medium": 7, "high": 5}
SOAK_SLACK = 2.0  # mm: skip a final soak smaller than this
ONE_THIRD_DUE = 1.5  # blade / deck height at which a cut takes the full 1/3


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


def third_floor(blade: float, deck: list[float] | tuple[float, ...] | None = None) -> float:
    """Lowest deck notch that cuts off no more than 1/3 of the blade as it stands now.

    The blade grows after each cut, so this uses the estimated (or measured) blade height,
    not the last deck setting: a taller blade means a higher floor.
    """
    notches = sorted(deck if deck is not None else DECK)
    floor = blade * 2 / 3
    return next((n for n in notches if n >= floor - 1e-9), notches[-1])


def cut_height(
    set_h: float,
    target: float,
    deck: list[float] | tuple[float, ...] | None = None,
    blade: float | None = None,
) -> float:
    """Deck notch for the next cut.

    The season target, but: no more than 1/3 of the blade, and no more than one notch
    below the last deck setting per cut (3.5 -> 3.0 -> 2.5).
    """
    notches = sorted(deck if deck is not None else DECK)
    cut = max(target, third_floor(set_h if blade is None else blade, notches))
    if cut < set_h - 1e-9:
        one_down = max((n for n in notches if n < set_h - 1e-9), default=notches[0])
        cut = max(cut, one_down)
    return cut


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


def melt_cap(tmax: float, yard: Yard | None = None) -> float:
    y = yard or Yard()
    return max(0.0, float(tmax)) * y.melt_factor_mm_per_c


def step_moisture(
    soil: float, pack: float, day: Day, manual: float, yard: Yard | None = None, frozen: bool | None = None
) -> tuple[float, float]:
    """One day: freezing precip → pack; part of the melt + liquid + irrigation → soil; then ET.

    On frozen ground only melt_soak_fraction of the rain soaks in. frozen = soil 6 cm daily mean
    at or below 0 °C; when that is unknown (None), snow on the ground at the start of the day.
    """
    y = yard or Yard()
    soil, pack = float(soil), float(pack)
    precip, manual = float(day.rain), float(manual)
    if day.tmax <= 0:
        pack += precip
        soil = step_balance(soil, 0.0, manual, 0.0, y.capacity_mm)
        return soil, pack
    if frozen is None:
        frozen = pack > 0
    melt = min(pack, melt_cap(day.tmax, y))
    pack -= melt
    rain = precip * (y.melt_soak_fraction if frozen else 1.0)
    soil = step_balance(soil, rain + melt * y.melt_soak_fraction, manual, et_mm(day.tmax, day.tmin, day.date, y), y.capacity_mm)
    return soil, pack


def replay_moisture(
    days: list[Day],
    start_soil: float = 15.0,
    start_pack: float = 0.0,
    manuals: dict[str, float] | None = None,
    yard: Yard | None = None,
    since: str | None = None,
    frozen: dict[str, bool] | None = None,
) -> tuple[float, float]:
    y, manuals, frozen = yard or Yard(), manuals or {}, frozen or {}
    soil, pack = float(start_soil), float(start_pack)
    for d in days:
        if since is not None and d.date < since:
            continue
        soil, pack = step_moisture(soil, pack, d, manuals.get(d.date, 0.0), y, frozen.get(d.date))
    return soil, pack


def consistently_below(vals: list[float], cap: float) -> bool:
    if not vals:
        return False
    need = max(1, -(-len(vals) * 7 // 10))
    return sum(v < cap for v in vals) >= need


def consistently_at_least(vals: list[float], floor: float) -> bool:
    if not vals:
        return False
    need = max(1, -(-len(vals) * 7 // 10))
    return sum(v >= floor for v in vals) >= need


def growth_from_highs(highs: list[float]) -> str:
    if not highs:
        return "low"
    mean = sum(highs) / len(highs)
    if mean < 15:
        return "low"
    if mean <= 22:
        return "medium"
    return "high"


def winter_status(highs: list[float], lows: list[float]) -> int:
    """Fall step from the 7-day highs: 0 summer, 1 slowing (< 15 °C), 2 cold (< 8 °C).

    A frost night alone does not stop growth, so lows do not set a step here. Step 3
    (dormant, all off) comes from soil temperature in lawn.season.
    """
    if consistently_below(highs, 8):
        return 2
    if consistently_below(highs, 15):
        return 1
    return 0


def spring_heights(yard: Yard | None = None) -> tuple[float, ...]:
    y = yard or Yard()
    return tuple(snap_deck(h, y.mower_deck) for h in y.spring_heights_in)


def spring_status(
    highs: list[float], lows: list[float], pack_mm: float, yard: Yard | None = None
) -> int:
    y = yard or Yard()
    if any(t <= 0 for t in lows) or pack_mm > y.spring_pack_clear_mm:
        return 0
    if consistently_below(highs, y.spring_green_high_c):
        return 0
    if consistently_at_least(highs, y.spring_summer_high_c) and pack_mm <= 0.05:
        return 2
    if consistently_at_least(highs, y.spring_green_high_c):
        return 1
    return 0


def season_height(winter: int, spring: int, yard: Yard | None = None) -> float:
    y = yard or Yard()
    wh, sh = heights(y), spring_heights(y)
    if winter >= 3:
        return wh[3]
    if winter >= 2:
        return wh[2]
    if winter >= 1:
        return wh[1]
    # Winter clear: spring ladder (or summer height)
    return sh[min(max(spring, 0), len(sh) - 1)]


def in_spring_season(iso: str | None) -> bool:
    if not iso or len(iso) < 7:
        return False
    return iso[5:7] in {"03", "04", "05", "06"}


def decide_mow(
    days_since: int,
    growth: str,
    rain_24_48: float,
    watering_today: bool,
    winter: int = 0,
    interval: dict[str, int] | None = None,
    major_rain: float = MAJOR_RAIN,
    watering_tomorrow: bool = False,
    height: float | None = None,
    target: float | None = None,
    blade: float | None = None,
) -> bool:
    if days_since <= 0 or watering_today:
        return False
    if winter >= 3:
        return False  # dormant: all off
    if height is not None and target is not None and height > target + 1e-9:
        # Step-down cut (3.5 -> 3.0 -> 2.5), with a few days to recover between steps.
        return days_since >= STEP_GAP_DAYS
    if blade is not None and height is not None and blade >= height * ONE_THIRD_DUE:
        return True  # the next cut already takes the full 1/3
    if winter >= 2:
        return False  # cold: cut only to step down or at the 1/3 limit
    gap = (interval or INTERVAL)[growth]
    close = days_since >= max(gap - 2, 3)
    due = days_since >= gap
    if watering_tomorrow and (close or due):
        return True
    if close and rain_24_48 >= major_rain:
        return True
    if close and winter >= 1:
        return True
    return due


STEP_GAP_DAYS = 3


def rain_soon(days: list[Day], i: int) -> float:
    return sum(d.rain for d in days[i + 1 : i + 3])


def water_mm(balance: float, scheduled: float, coming: float, yard: Yard | None = None) -> tuple[float, bool]:
    """Normal rule: logged water first; skip if big rain is coming; one cycle below the trigger."""
    y = yard or Yard()
    if scheduled:
        return scheduled, True
    if coming >= y.major_rain_mm:
        return 0.0, False
    if balance < y.trigger_mm:
        return cycle_mm(y), True
    return 0.0, False


def fall_target(winter: int, iso: str, dormant: str | None, hs: tuple[float, ...]) -> float:
    """3.5 summer; 3.0 when highs slow or growth stops in <= 14 days; 2.5 when cold or <= 7 days."""
    left = (date.fromisoformat(dormant) - date.fromisoformat(iso)).days if dormant else None
    if winter >= 2 or (left is not None and left <= FINAL_DAYS):
        return hs[2]
    if winter >= 1 or (left is not None and left <= SLOW_DAYS):
        return hs[1]
    return hs[0]


SLOW_DAYS = 14
FINAL_DAYS = 7


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
    next_water_mm: float = 0.0
    following_water_mm: float = 0.0
    next_mow_height: float | None = None
    final_soak_today: bool = False
    mows: list = field(default_factory=list)  # [date, deck inches, blade inches before]
    waters: list = field(default_factory=list)  # [date, mm, kind]


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


def note(
    out: Schedule,
    when: str,
    watering: bool,
    mow: bool,
    winter: int,
    water: float = 0.0,
    cut_to: float | None = None,
) -> None:
    if watering and out.next_water_date is None:
        out.next_water_date = when
        out.next_water_mm = water
    elif watering and out.following_water_date is None:
        out.following_water_date = when
        out.following_water_mm = water
    if mow and out.next_mow_date is None:
        out.next_mow_date = when
        out.next_mow_height = cut_to


def season_end(days: list[Day]) -> tuple[str | None, str | None]:
    last_mow = last_water = None
    for d in days:
        if last_mow is None and d.tmax < 8:
            last_mow = d.date
        if d.tmin <= 0:
            return last_mow or d.date, d.date
    return last_mow, last_water


def default_growth(days: list[Day], rate: float) -> dict[str, float]:
    """Growth per day from air only (soil taken as mean air + 0.5 °C) when no fall plan is given."""
    from lawn.season import growth_in

    return {d.date: growth_in((d.tmax + d.tmin) / 2, (d.tmax + d.tmin) / 2 + 0.5, rate) for d in days}


def project_schedule(
    days: list[Day],
    start_balance: float,
    days_since_mow: int,
    growth: str,
    scheduled_water: dict[str, float],
    yard: Yard | None = None,
    *,
    height: float | None = None,
    blade: float | None = None,
    grow: dict[str, float] | None = None,
    cleanup: str | None = None,
    dormant: str | None = None,
) -> Schedule:
    """Walk the forecast day by day.

    height: deck setting of the last cut. blade: blade height at the start of days[0].
    grow: inches of growth per day. cleanup: hose cleanup day (final soak that morning,
    no water after it). dormant: first day growth has stopped (nothing from that day on).
    """
    y = yard or Yard()
    hs = heights(y)
    out = Schedule(None, None, None, None, False, False, 0.0, hs[0], 0, start_balance)
    balance, since = start_balance, days_since_mow
    set_h = y.mower_height_inches if height is None else height
    blade_h = set_h if blade is None else blade
    grow = default_growth(days, y.growth_rate_in_day) if grow is None else grow

    def plan_water(i: int, bal: float) -> tuple[float, bool, str]:
        day = days[i]
        logged = scheduled_water.get(day.date, 0.0)
        if logged:
            return logged, True, "logged"
        if (dormant and day.date >= dormant) or (cleanup and day.date > cleanup):
            return 0.0, False, "off"
        if cleanup == day.date:
            need = y.capacity_mm - bal
            return (need, True, "final soak") if need >= SOAK_SLACK else (0.0, False, "full")
        mm, on = water_mm(bal, 0.0, rain_soon(days, i), y)
        return mm, on, "cycle"

    winters = []
    for i, day in enumerate(days):
        slice7 = days[i : i + 7]
        w = winter_status([d.tmax for d in slice7], [d.tmin for d in slice7])
        winters.append(3 if dormant and day.date >= dormant else w)
    base = [fall_target(w, d.date, dormant, hs) for w, d in zip(winters, days)]
    notches = sorted(y.mower_deck)

    def up_one(h: float) -> float:
        return min((n for n in notches if n > h + 1e-9), default=h)

    # Look ahead: if 2.5 is needed within STEP_GAP_DAYS, the 3.0 step starts today.
    targets = [
        min([base[i]] + [up_one(base[k]) for k in range(i + 1, min(len(days), i + 1 + STEP_GAP_DAYS))])
        for i in range(len(days))
    ]

    for i, day in enumerate(days):
        winter = winters[i]
        coming = rain_soon(days, i)
        manual, watering, kind = plan_water(i, balance)
        et = et_mm(day.tmax, day.tmin, day.date, y)
        after = step_balance(balance, day.rain, manual if watering else 0.0, et, y.capacity_mm)
        tomorrow = i + 1 < len(days) and plan_water(i + 1, after)[1]
        target = targets[i]
        cut_to = cut_height(set_h, target, y.mower_deck, blade_h)
        mow = decide_mow(
            since, growth, coming, watering, winter, y.mow_interval_days, y.major_rain_mm, tomorrow,
            height=set_h, target=target, blade=blade_h,
        )
        note(out, day.date, watering, mow, winter, manual if watering else 0.0, cut_to)
        if watering:
            out.waters.append([day.date, round(manual, 2), kind])
            if kind in ("final soak", "logged") and cleanup == day.date:
                out.last_water_of_season = day.date
        if mow:
            out.mows.append([day.date, cut_to, round(blade_h, 2)])
            if dormant:
                out.last_mow_of_season = day.date
        if i == 0:
            out.should_mow = mow
            out.should_water = watering
            out.target_water_mm = manual if watering else 0.0
            out.final_soak_today = kind == "final soak"
            out.mower_height = cut_to
            out.winter = winter
        balance = after
        # Cut in the evening: tomorrow starts at the new deck height, then grows.
        if mow:
            set_h = blade_h = cut_to
        blade_h += grow.get(day.date, 0.0)
        since = 0 if mow else since + 1
    if dormant and days and dormant > days[-1].date:
        out.last_mow_of_season = None  # more cuts may come after the window
    out.end_balance = balance
    return out
