"""Fall season: grass growth, soil temperature, dormancy and the hose cleanup date.

Sources for the constants are listed next to each one. Values marked "fitted" come
from 2011-2025 ERA5 data for this yard (Open-Meteo archive).
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from lawn.models import Day, Yard

# PACE Turf growth potential (Gelernter & Stowell 2005), cool-season grass, daily mean air °C.
GP_OPT_C = 20.0
GP_SPREAD_C = 5.5
# Shoot growth slows below 10 °C soil and stops near 4 °C soil (extension guidance).
SOIL_FULL_C = 10.0
SOIL_STOP_C = 4.0
# Soil (6 cm) follows daily mean air with a lag. Fitted: 7-day-ahead error 1.7 °C.
SOIL_ALPHA = 0.5
SOIL_OFFSET_C = 0.5
# Ice growth with an air film (Stefan's law plus surface resistance).
ICE_K = 2.22  # W/m·K, conductivity of ice
ICE_RHO = 917.0  # kg/m³, density of ice
ICE_L = 334000.0  # J/kg, latent heat of fusion
AIR_H = 15.0  # W/m²·K, still air + clear-night radiation on a hose (high end = early date)
FALL_MONTHS = range(8, 13)


def growth_potential(tmean_c: float) -> float:
    """0..1, 1 at a daily mean air temperature of 20 °C."""
    return math.exp(-0.5 * ((tmean_c - GP_OPT_C) / GP_SPREAD_C) ** 2)


def soil_factor(tsoil_c: float) -> float:
    """0 at 4 °C soil, 1 at 10 °C soil and above, straight line between."""
    return min(1.0, max(0.0, (tsoil_c - SOIL_STOP_C) / (SOIL_FULL_C - SOIL_STOP_C)))


def growth_in(tmean_c: float, tsoil_c: float, rate_in_day: float) -> float:
    """Blade growth in inches for one day."""
    return rate_in_day * growth_potential(tmean_c) * soil_factor(tsoil_c)


def ice_degree_hours(ice_mm: float, h: float = AIR_H) -> float:
    """Freezing degree-hours (°C·h) to freeze ice_mm of still water.

    rho·L·(d²/2k + d/h) = (freezing °C)·(seconds). The d/h term is the air film; without it
    (pure Stefan) 6 mm would freeze in under 1 °C·h, which is not what hoses do.
    """
    d = ice_mm / 1000.0
    return ICE_RHO * ICE_L * (d * d / (2 * ICE_K) + d / h) / 3600.0


def soil_lag(prev_c: float, air_mean_c: float) -> float:
    return prev_c + SOIL_ALPHA * (air_mean_c + SOIL_OFFSET_C - prev_c)


def hose_cleanup_day(
    hourly: list[tuple[str, float]], need: float, margin_c: float, start: str | None = None
) -> tuple[str | None, str | None]:
    """First freeze spell that can freeze the hose. Returns (cleanup date, hit time).

    Running sum of degree-hours below 0 °C, with temp - margin (ground-level air on clear
    nights runs colder than 2 m air). Warm hours melt it back at the same rate.
    The cleanup date is the day before the spell starts, or the same day if it starts at noon or later.
    """
    fdh = 0.0
    spell = None
    for t, temp in hourly:
        if start and t < start:
            continue
        fdh = max(0.0, fdh - (temp - margin_c))
        if fdh == 0.0:
            spell = None
        elif spell is None:
            spell = t
        if fdh >= need:
            s = datetime.fromisoformat(spell)
            day = s.date() if s.hour >= 12 else s.date() - timedelta(days=1)
            return day.isoformat(), t
    return None, None


def dormant_day(soil: dict[str, float], below_c: float, run_days: int, start: str | None = None) -> str | None:
    """First day of the first run of run_days days with daily mean soil below below_c."""
    run = 0
    days = sorted(d for d in soil if start is None or d >= start)
    for i, d in enumerate(days):
        run = run + 1 if soil[d] < below_c else 0
        if run >= run_days:
            return days[i - run_days + 1]
    return None


def percentile_md(mds: list[str | None], pct: float) -> str | None:
    """Month-day by which pct % of years had the event. Years with no event sort last."""
    if not mds:
        return None
    vals = sorted(m or "99-99" for m in mds)
    k = max(0, math.ceil(len(vals) * pct / 100.0) - 1)
    return None if vals[k] == "99-99" else vals[k]


def climate_dates(clim: dict, after: str, yard: Yard) -> tuple[str | None, str | None]:
    """(hose cleanup, grass stops) as ISO dates this year, from past years, counted from `after`.

    Hose: the date by which hose_risk_pct % of years needed the cleanup (early = safe).
    Grass: the median year.
    """
    need = ice_degree_hours(yard.hose_ice_in * 25.4)
    md = after[5:]
    hose, dorm = [], []
    for y, rec in sorted((clim.get("years") or {}).items()):
        t0 = datetime.fromisoformat(rec["start"])
        hours = [((t0 + timedelta(hours=i)).isoformat(timespec="minutes"), a) for i, a in enumerate(rec["air"])]
        start = f"{y}-{md}"
        h, _ = hose_cleanup_day([(t, a) for t, a in hours if a is not None], need, yard.hose_margin_c, start)
        hose.append(h[5:] if h else None)
        soil: dict[str, list[float]] = defaultdict(list)
        for (t, _), s in zip(hours, rec["soil"]):
            if s is not None:
                soil[t[:10]].append(s)
        daily = {d: sum(v) / len(v) for d, v in soil.items()}
        dd = dormant_day(daily, yard.dormant_soil_c, yard.dormant_days, start)
        dorm.append(dd[5:] if dd else None)
    year = after[:4]
    h_md, d_md = percentile_md(hose, yard.hose_risk_pct), percentile_md(dorm, 50)
    return (f"{year}-{h_md}" if h_md else None), (f"{year}-{d_md}" if d_md else None)


def synth_hourly(days: list[Day]) -> list[tuple[str, float]]:
    """Hourly air from daily min/max (min at 06:00, max at 15:00, cosine between)."""
    out = []
    for d in days:
        lo, hi = d.tmin, d.tmax
        for h in range(24):
            # 06 -> 15 rising, 15 -> 06 falling
            if 6 <= h <= 15:
                f = (1 - math.cos(math.pi * (h - 6) / 9)) / 2
            else:
                k = (h - 15) % 24
                f = (1 + math.cos(math.pi * k / 15)) / 2
            out.append((f"{d.date}T{h:02d}:00", lo + (hi - lo) * f))
    return out


@dataclass
class FallPlan:
    soil_c: dict[str, float] = field(default_factory=dict)  # daily mean soil 6 cm
    soil_basis: dict[str, str] = field(default_factory=dict)  # "measured" / "forecast" / "model"
    air_c: dict[str, float] = field(default_factory=dict)  # daily mean air
    grow_in: dict[str, float] = field(default_factory=dict)  # inches of blade growth per day
    frost_nights: list[str] = field(default_factory=list)
    hose_date: str | None = None
    hose_basis: str = ""
    dormant_date: str | None = None
    dormant_basis: str = ""
    cleanup_date: str | None = None
    cleanup_basis: str = ""
    blade_in: float = 0.0
    blade_basis: str = ""
    implied_rate: float | None = None
    ice_need_fdh: float = 0.0
    extra_days: list[Day] = field(default_factory=list)  # Open-Meteo days past the OpenWeather forecast

    def as_dict(self, today: str) -> dict:
        ahead = sorted(d for d in self.soil_c if d >= today)
        return {
            "soil_now_c": round(self.soil_c[today], 1) if today in self.soil_c else None,
            "soil_now_basis": self.soil_basis.get(today, ""),
            "soil_week_c": [[d, round(self.soil_c[d], 1), self.soil_basis.get(d, "")] for d in ahead[:16]],
            "grow_week_in": [[d, round(self.grow_in.get(d, 0.0), 3)] for d in ahead[:16]],
            "frost_nights": self.frost_nights,
            "hose_date": self.hose_date,
            "hose_basis": self.hose_basis,
            "dormant_date": self.dormant_date,
            "dormant_basis": self.dormant_basis,
            "cleanup_date": self.cleanup_date,
            "cleanup_basis": self.cleanup_basis,
            "blade_in": round(self.blade_in, 2),
            "blade_basis": self.blade_basis,
            "implied_rate_in_day": None if self.implied_rate is None else round(self.implied_rate, 3),
            "ice_need_fdh": round(self.ice_need_fdh, 1),
        }


def _daily_means(hourly: list[tuple[str, float | None]]) -> dict[str, float]:
    acc: dict[str, list[float]] = defaultdict(list)
    for t, v in hourly:
        if v is not None:
            acc[t[:10]].append(v)
    return {d: sum(v) / len(v) for d, v in acc.items() if len(v) >= 12}


def blade_estimate(yard: Yard, today: str, grow: dict[str, float]) -> tuple[float, str, float | None]:
    """Blade height this morning: last cut (or later measurement) + growth on each day since."""
    base_day, base_h, basis = yard.last_mow_date, yard.mower_height_inches, "cut"
    if yard.mow_log:
        base_day = max(yard.mow_log)
        base_h = yard.mow_log[base_day]
    measured = {d: h for d, h in (yard.height_log or {}).items() if d >= base_day and d <= today}
    implied = None
    if measured:
        m_day = max(measured)
        sum_g = sum(grow.get(d, 0.0) for d in _days_between(base_day, m_day))
        potential = sum_g / yard.growth_rate_in_day if yard.growth_rate_in_day > 0 else 0.0
        if potential >= 0.5 and m_day != base_day:
            implied = max(0.0, (measured[m_day] - base_h) / potential)
        base_day, base_h, basis = m_day, measured[m_day], "measured"
    days = _days_between(base_day, today)
    known = [grow[d] for d in days if d in grow]
    fill = sum(known) / len(known) if known else 0.0
    h = base_h + sum(grow.get(d, fill) for d in days)
    return h, f"{basis} {base_h:g} in on {base_day} + growth", implied


def _days_after(rows: list, last: str) -> list[Day]:
    """Whole days (24 hours of air) after `last`, as Day rows: min/max air and rain."""
    acc: dict[str, list] = defaultdict(list)
    for r in rows:
        if r[0][:10] > last and r[1] is not None:
            acc[r[0][:10]].append((r[1], (r[3] if len(r) > 3 else 0.0) or 0.0))
    return [
        Day(date=d, tmax=max(a for a, _ in v), tmin=min(a for a, _ in v), rain=round(sum(x for _, x in v), 2))
        for d, v in sorted(acc.items())
        if len(v) == 24
    ]


def _days_between(after: str, before: str) -> list[str]:
    """ISO dates strictly after `after` and strictly before `before`."""
    a, b = date.fromisoformat(after), date.fromisoformat(before)
    return [(a + timedelta(days=i)).isoformat() for i in range(1, (b - a).days)]


def fall_plan(
    yard: Yard,
    today: str,
    history: list[Day],
    forecast: list[Day],
    om: dict | None,
    clim: dict | None,
) -> FallPlan:
    """Join Open-Meteo hourly air/soil, the OpenWeather days and the climate file into one plan."""
    p = FallPlan(ice_need_fdh=ice_degree_hours(yard.hose_ice_in * 25.4))
    if om and om.get("hourly"):
        rows = om["hourly"]
        hourly_air = [(r[0], r[1]) for r in rows if r[1] is not None]
        soil_obs = _daily_means([(r[0], r[2]) for r in rows])
        p.extra_days = _days_after(rows, forecast[-1].date if forecast else today)
    else:
        hourly_air = synth_hourly(history + forecast)
        soil_obs = {}
    p.air_c = _daily_means(hourly_air)
    for d in history + forecast:  # days Open-Meteo did not cover
        p.air_c.setdefault(d.date, (d.tmax + d.tmin) / 2)

    # Soil: measured/forecast where present, lag model past the end of the soil forecast.
    prev = None
    for d in sorted(p.air_c):
        if d in soil_obs:
            prev = soil_obs[d]
            p.soil_basis[d] = "measured" if d < today else "forecast"
        else:
            prev = p.air_c[d] + SOIL_OFFSET_C if prev is None else soil_lag(prev, p.air_c[d])
            p.soil_basis[d] = "model"
        p.soil_c[d] = prev
    p.grow_in = {d: growth_in(p.air_c[d], p.soil_c[d], yard.growth_rate_in_day) for d in p.soil_c}

    lows: dict[str, float] = {}
    for t, a in hourly_air:
        lows[t[:10]] = min(a, lows.get(t[:10], a))
    for d in forecast:
        lows[d.date] = min(d.tmin, lows.get(d.date, d.tmin))
    p.frost_nights = sorted(d for d, lo in lows.items() if d >= today and lo <= yard.frost_c)

    # Hose: count from noon yesterday so a spell that started last night still counts.
    since = (date.fromisoformat(today) - timedelta(days=1)).isoformat() + "T12:00"
    hose, hit = hose_cleanup_day(hourly_air, p.ice_need_fdh, yard.hose_margin_c, since)
    end = max(p.air_c)
    fall = int(today[5:7]) in FALL_MONTHS
    clim_hose = clim_dorm = None
    if fall and clim:
        after = (date.fromisoformat(end) + timedelta(days=1)).isoformat()
        clim_hose, clim_dorm = climate_dates(clim, after, yard)
    if hose:
        p.hose_date, p.hose_basis = max(hose, today), f"forecast: {yard.hose_ice_in:g} in of ice by {hit.replace('T', ' ')}"
    elif clim_hose:
        p.hose_date, p.hose_basis = clim_hose, f"climate: {yard.hose_risk_pct:g}% of past years by then (forecast clear to {end})"

    start = (date.fromisoformat(today) - timedelta(days=yard.dormant_days - 1)).isoformat()
    dorm = dormant_day(p.soil_c, yard.dormant_soil_c, yard.dormant_days, start)
    if dorm:
        kinds = {p.soil_basis.get(d) for d in p.soil_c if dorm <= d}
        p.dormant_date = max(dorm, today) if dorm <= today else dorm
        p.dormant_basis = "soil " + ("model" if "model" in kinds else "forecast") + f": {yard.dormant_days} days below {yard.dormant_soil_c:g} °C"
    elif clim_dorm:
        p.dormant_date, p.dormant_basis = clim_dorm, f"climate: median past year (soil forecast/model clear to {end})"

    if fall:
        pick = [(d, b) for d, b in ((p.hose_date, "hose ice"), (p.dormant_date, "grass stops")) if d]
        if pick:
            d, why = min(pick)
            p.cleanup_date = max(d, today)
            p.cleanup_basis = why
    p.blade_in, p.blade_basis, p.implied_rate = blade_estimate(yard, today, p.grow_in)
    return p
