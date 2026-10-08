from __future__ import annotations

import json
import os
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from lawn.checklist import evaluate_checklist
from lawn.jev import ask_jev
from lawn.models import DailyReport, Day, LawnActionItems, ScheduleOut, Yard
from lawn.rules import (
    cut_height,
    cycle_mm,
    days_since_mow,
    et_mm,
    growth_from_highs,
    in_spring_season,
    manuals_mm,
    project_schedule,
    replay_moisture,
    season_end,
    season_height,
    spring_status,
    step_balance,
)
from lawn.season import fall_plan
from lawn.weather import fetch_climate, fetch_open_meteo, fetch_weather

ROOT = Path(__file__).resolve().parent.parent
PUBLISH = Path("/var/www/grass")
LEDGER = ROOT / "ledger.json"
WEATHER_CACHE = ROOT / "weather_cache.json"
CLIMATE_CACHE = ROOT / "climate_cache.json"
CLIMATE_YEARS = 15
CST = ZoneInfo("America/Regina")
YES = 0.65


def load_env() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def load_yard() -> Yard:
    path = ROOT / "yard.json"
    if not path.exists():
        return Yard()
    raw = json.loads(path.read_text())
    yard = Yard.model_validate(raw)
    # One-time migrate: old yards only had last_mow_date.
    if "mow_log" not in raw and yard.last_mow_date:
        yard = yard.model_copy(
            update={"mow_log": {yard.last_mow_date: float(yard.mower_height_inches)}}
        )
        path.write_text(yard.model_dump_json(indent=2))
    return yard


def save_yard(data: dict) -> Yard:
    from lawn.actions import yard_patch_from_actions

    payload = {k: v for k, v in data.items() if v is not None}
    if "actions" in payload:
        payload.update(yard_patch_from_actions(payload.pop("actions") or []))
    current = load_yard().model_dump()
    current.update(payload)
    yard = Yard.model_validate(current)
    (ROOT / "yard.json").write_text(yard.model_dump_json(indent=2))
    return yard


def load_saved() -> tuple[str | None, float | None, float]:
    path = ROOT / "lawn_state.json"
    if not path.exists():
        return None, None, 0.0
    data = json.loads(path.read_text())
    as_of = data.get("as_of")
    bal = data.get("current_water_balance_mm")
    pack = float(data.get("snowpack_mm") or 0.0)
    if not as_of or bal is None:
        return None, None, pack
    return str(as_of), float(bal), pack


def formula_signals(forecast, growth: str, yard: Yard) -> dict:
    rain48 = sum(d.rain for d in forecast[:3])
    freeze = 1.0 if any(d.tmin <= yard.frost_c for d in forecast[:7]) else 0.0  # frost warning only
    score = {"low": 0.3, "medium": 1.0, "high": 1.7}[growth]
    return {
        "growth": growth,
        "growth_score": score,
        "growth_confidence": 1.0,
        "significant_rain_24_48h": 1.0 if rain48 >= yard.major_rain_mm else 0.0,
        "should_mow_now": 0.0,
        "rain_covers_watering": 1.0 if rain48 >= yard.major_rain_mm else 0.0,
        "freeze_blowout_now": freeze,
        "mower_regime": {"low": "slowing", "medium": "summer", "high": "summer"}[growth],
        "mower_regime_confidence": 1.0,
        "model": "formula",
    }


def minutes_for(mm: float, y: Yard) -> float:
    if mm <= 0 or y.gpm <= 0 or y.sqft <= 0:
        return 0.0
    return round((mm * y.sqft * 0.09290304) / (y.gpm * 3.785411784), 1)


def feed_of(y: Yard, as_of: str, target_mm: float) -> dict:
    return {
        "address": y.address,
        "grass": y.grass,
        "facing": y.facing,
        "light": y.light,
        "sqft": y.sqft,
        "gpm": y.gpm,
        "cycle_minutes": y.cycle_minutes,
        "cycle_mm": cycle_mm(y),
        "capacity_mm": y.capacity_mm,
        "trigger_mm": y.trigger_mm,
        "kc": y.kc,
        "et_factor": y.et_factor,
        "mower_height_inches": y.mower_height_inches,
        "mower_max_inches": y.mower_max_inches,
        "mower_deck": list(y.mower_deck),
        "last_mow_date": y.last_mow_date,
        "target_water_minutes": minutes_for(target_mm, y),
        "as_of": as_of,
    }


def reason(
    balance: float,
    pack: float,
    growth: str,
    sched,
    loc: dict,
    jev: dict,
    y: Yard,
    spring: int,
    fall: dict | None = None,
) -> str:
    place = f"{loc.get('name')}, {loc.get('region')}"
    f = fall or {}
    next_mm = sched.next_water_mm or cycle_mm(y)
    water = (
        f"Next water {sched.next_water_date} ({next_mm:.1f} mm / {minutes_for(next_mm, y):g} min)"
        if sched.next_water_date else "No water in the forecast window"
    )
    mow = (
        f"Next mow {sched.next_mow_date} at {sched.next_mow_height:g} in"
        if sched.next_mow_date and sched.next_mow_height else "No mow in the forecast window"
    )
    soil_c = f.get("soil_now_c")
    return (
        f"{place}. Soil water {balance:.1f} of {y.capacity_mm:g} mm"
        + (f", soil {soil_c:.1f} °C" if soil_c is not None else "")
        + f". Growth {growth}; blade about {f.get('blade_in', 0):.2f} in. {water}. {mow}. "
        f"Hose cleanup {f.get('cleanup_date') or 'not dated'} ({f.get('cleanup_basis') or '—'}). "
        f"Grass stops {f.get('dormant_date') or 'not dated'}. "
        f"Frost nights: {', '.join(f.get('frost_nights') or []) or 'none'}. Winter {sched.winter} / spring {spring}."
    )


def merge(
    sched,
    jev: dict,
    balance: float,
    loc: dict,
    yard: Yard | None = None,
    as_of: str | None = None,
    *,
    pack: float = 0.0,
    spring: int = 0,
    checklist: list[dict] | None = None,
    watered_today_mm: float = 0.0,
    recent_water_mm: float = 0.0,
    fall: dict | None = None,
) -> DailyReport:
    y = yard or Yard()
    # All off only when the soil says growth has stopped. A frost night is a warning, not a stop.
    shutdown = sched.winter >= 3
    final_soak = getattr(sched, "final_soak_today", False)
    skip_water = jev["rain_covers_watering"] >= YES and not final_soak
    watered = watered_today_mm > 0
    plan_water, plan_mm = sched.should_water, sched.target_water_mm
    should_water = plan_water and not skip_water and not watered and not shutdown
    should_mow = (sched.should_mow or jev["should_mow_now"] >= YES) and not should_water and not watered and not shutdown
    spring_active = in_spring_season(as_of)
    if spring_active and spring == 0 and sched.winter <= 1 and not shutdown:
        should_mow = False  # dormant/thaw: don't cut
    target = plan_mm if should_water else 0.0
    spring_for_height = spring if spring_active else (2 if sched.winter == 0 else 0)
    if spring_active:
        height = cut_height(y.mower_height_inches, season_height(sched.winter, spring_for_height, y), y.mower_deck)
    else:
        # The projection already applied the fall ladder, the 1/3 rule and one notch per cut.
        height = sched.mower_height
    when = as_of or ""
    return DailyReport(
        current_water_balance_mm=round(balance, 2),
        snowpack_mm=round(pack, 2),
        estimated_growth_rate=jev["growth"],
        lawn_action_items=LawnActionItems(
            should_water=should_water,
            target_water_amount_mm=round(target, 2),
            should_mow=should_mow,
            recommended_mower_height_inches=height,
            is_winter_shutdown_triggered=shutdown,
        ),
        reasoning_summary=reason(balance, pack, jev["growth"], sched, loc, jev, y, spring, fall),
        schedule=ScheduleOut(
            next_water_date=sched.next_water_date,
            following_water_date=sched.following_water_date,
            next_water_mm=round(getattr(sched, "next_water_mm", 0.0), 2),
            following_water_mm=round(getattr(sched, "following_water_mm", 0.0), 2),
            next_mow_date=sched.next_mow_date,
            next_mow_height=getattr(sched, "next_mow_height", None),
            last_water_of_season=sched.last_water_of_season,
            last_mow_of_season=sched.last_mow_of_season,
            frost_watch_date=sched.frost_watch_date,
            final_soak_mm=round(sched.target_water_mm, 2) if final_soak else 0.0,
            mows=list(getattr(sched, "mows", [])),
            waters=list(getattr(sched, "waters", [])),
        ),
        fall=dict(fall or {}),
        winter_phase=sched.winter,
        spring_phase=spring,
        checklist=list(checklist or []),
        jev=jev,
        as_of=as_of,
        feed=feed_of(y, when, target),
    )


def now_cst() -> str:
    return datetime.now(CST).isoformat(timespec="minutes")


def record_ledger(entry: dict, path: Path | None = None) -> list[dict]:
    dest = path or LEDGER
    rows = json.loads(dest.read_text()) if dest.exists() else []
    if entry.get("as_of"):
        rows = [r for r in rows if r.get("as_of") != entry["as_of"]]
    rows.insert(0, entry)
    dest.write_text(json.dumps(rows, indent=2))
    return rows


def frozen_by_day(om: dict | None) -> dict[str, bool]:
    """Frozen ground per day: Open-Meteo soil 6 cm daily mean at or below 0 °C. Days with no soil reading are left out."""
    temps: dict[str, list[float]] = {}
    for h in (om or {}).get("hourly") or []:
        if len(h) > 2 and h[2] is not None:
            temps.setdefault(h[0][:10], []).append(h[2])
    return {d: sum(v) / len(v) <= 0 for d, v in temps.items()}


def rain_by_day(history: list[Day], om: dict | None, today: str, now: str) -> dict[str, tuple[float, bool]]:
    """Recorded rain (mm, final?) per day: full past days from OpenWeather, today so far from Open-Meteo hourly."""
    rain = {d.date: (round(d.rain, 2), True) for d in history}
    hours = [h for h in (om or {}).get("hourly") or [] if h[0][:10] == today and h[0][:13] <= now[:13]]
    if hours:
        rain[today] = (round(sum(h[3] or 0.0 for h in hours), 2), False)
    return rain


def record_rain(rain: dict[str, tuple[float, bool]], path: Path | None = None) -> list[dict]:
    """Write recorded rain onto ledger rows. A finished day is never replaced by a partial count."""
    dest = path or LEDGER
    rows = json.loads(dest.read_text()) if dest.exists() else []
    for r in rows:
        got = rain.get(r.get("as_of"))
        if got and not (r.get("rain_final") and not got[1]):
            r["rain_mm"], r["rain_final"] = got
    dest.write_text(json.dumps(rows, indent=2))
    return rows


def ledger_entry(report: DailyReport, ran_at: str) -> dict:
    a = report.lawn_action_items
    s = report.schedule
    j = report.jev or {}
    f = report.feed or {}
    return {
        "ran_at": ran_at,
        "as_of": report.as_of,
        "balance_mm": report.current_water_balance_mm,
        "pack_mm": report.snowpack_mm,
        "watered_today_mm": f.get("watered_today_mm", 0.0),
        "growth": report.estimated_growth_rate,
        "should_water": a.should_water,
        "should_mow": a.should_mow,
        "target_mm": a.target_water_amount_mm,
        "target_minutes": f.get("target_water_minutes"),
        "cycle_minutes": f.get("cycle_minutes"),
        "gpm": f.get("gpm"),
        "next_water": s.next_water_date,
        "following_water": s.following_water_date,
        "next_mow": s.next_mow_date,
        "height": a.recommended_mower_height_inches,
        "shutdown": a.is_winter_shutdown_triggered,
        "cleanup": (report.fall or {}).get("cleanup_date"),
        "dormant": (report.fall or {}).get("dormant_date"),
        "soil_c": (report.fall or {}).get("soil_now_c"),
        "blade_in": (report.fall or {}).get("blade_in"),
        "jev_growth": j.get("growth_score"),
        "jev_rain48": j.get("significant_rain_24_48h"),
        "jev_freeze": j.get("freeze_blowout_now"),
    }


def publish() -> None:
    if not PUBLISH.exists():
        return
    PUBLISH.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "lawn_state.json", "ledger.json", "yard.json"):
        src = ROOT / name
        if src.exists():
            shutil.copy2(src, PUBLISH / name)
    assets = PUBLISH / "assets"
    assets.mkdir(exist_ok=True)
    for css in (ROOT / "assets").glob("*.css"):
        shutil.copy2(css, assets / css.name)


def today_cst() -> str:
    return datetime.now(CST).date().isoformat()


def load_weather(key: str, yard: Yard, refresh: bool = False) -> tuple[dict, list[Day], list[Day], dict | None]:
    """Fetch weather once per CST day; later runs that day reuse the cache.

    Returns OpenWeather (location, history, forecast) and Open-Meteo hourly air/soil (or None).
    """
    c = json.loads(WEATHER_CACHE.read_text()) if WEATHER_CACHE.exists() else {}
    fresh = not refresh and c.get("day") == today_cst()
    if fresh:
        days = lambda k: [Day.model_validate(d) for d in c[k]]
        loc, history, forecast = c["loc"], days("history"), days("forecast")
    else:
        loc, history, forecast = fetch_weather(key, yard)
    om = c.get("open_meteo") if fresh else None
    if om is None:
        try:
            om = fetch_open_meteo(yard)
        except Exception as e:  # soil/hourly data is an add-on: fall back to daily min/max
            print(f"open-meteo: {type(e).__name__}: {e}")
            om = None
    WEATHER_CACHE.write_text(json.dumps({
        "day": today_cst(),
        "loc": loc,
        "history": [d.model_dump() for d in history],
        "forecast": [d.model_dump() for d in forecast],
        "open_meteo": om,
    }))
    return loc, history, forecast, om


def load_climate(yard: Yard) -> dict | None:
    """Past falls for this yard. Fetched once, again only when a new year is complete or the yard moves."""
    last = datetime.now(CST).year - 1
    if CLIMATE_CACHE.exists():
        c = json.loads(CLIMATE_CACHE.read_text())
        if c.get("last") == last and c.get("lat") == yard.lat and c.get("lon") == yard.lon:
            return c
    try:
        c = fetch_climate(yard, last - CLIMATE_YEARS + 1, last)
    except Exception as e:
        print(f"climate: {type(e).__name__}: {e}")
        return json.loads(CLIMATE_CACHE.read_text()) if CLIMATE_CACHE.exists() else None
    CLIMATE_CACHE.write_text(json.dumps(c))
    return c


def replay_start(history: list[Day], yard: Yard) -> tuple[float, float, str | None]:
    """Soil/pack at the start of the oldest ledger day still inside the weather history.

    Replaying the whole history window each run means water logged late (after the
    day was already counted) still lands, and re-runs never count a day twice.
    """
    rows = json.loads(LEDGER.read_text()) if LEDGER.exists() else []
    first = history[0].date if history else None
    inside = [r for r in rows if first and r.get("as_of") and r.get("balance_mm") is not None and r["as_of"] >= first]
    if inside:
        r = min(inside, key=lambda r: r["as_of"])
        return float(r["balance_mm"]), float(r.get("pack_mm") or 0.0), r["as_of"]
    saved_as_of, saved_bal, saved_pack = load_saved()
    if saved_as_of is not None and saved_bal is not None:
        return saved_bal, saved_pack, saved_as_of
    return yard.prior_balance_mm, yard.prior_snowpack_mm, None


def run(refresh: bool = False) -> DailyReport:
    load_env()
    yard = load_yard()
    key = os.environ.get("OPENWEATHER_API_KEY") or os.environ["WEATHERAPI_KEY"]
    loc, history, forecast, om = load_weather(key, yard, refresh)
    today = date.fromisoformat(forecast[0].date)
    iso = today.isoformat()
    manuals = manuals_mm(yard)
    start_soil, start_pack, since = replay_start(history, yard)
    balance, pack = replay_moisture(
        history, start_soil=start_soil, start_pack=start_pack, manuals=manuals, yard=yard, since=since,
        frozen=frozen_by_day(om),
    )
    watered_today = manuals.get(iso, 0.0)
    since_mow = days_since_mow(today, yard.last_mow_date)
    highs = [d.tmax for d in forecast[:7]]
    lows = [d.tmin for d in forecast[:7]]
    growth = growth_from_highs(highs)
    if os.environ.get("JEV_ENABLED") == "1":
        jev = ask_jev(yard, loc, history, forecast, balance, since_mow)
        growth = jev["growth"]
    else:
        jev = formula_signals(forecast, growth, yard)

    # Soil temperature, blade height, frost nights, grass-stop and hose cleanup dates.
    fall = fall_plan(yard, iso, history, forecast, om, load_climate(yard))
    plan = {
        "height": yard.mower_height_inches,
        "blade": fall.blade_in,
        "grow": fall.grow_in,
        "cleanup": fall.cleanup_date,
        "dormant": fall.dormant_date,
    }
    # Plan over 16 days: OpenWeather days, then Open-Meteo days to the end of its forecast.
    days = forecast + fall.extra_days
    sched = project_schedule(days, balance, since_mow, growth, manuals, yard, **plan)
    if watered_today and len(days) > 1:
        # Today's water is done: every date comes from tomorrow on, starting from the watered soil.
        d0 = forecast[0]
        after = step_balance(balance, d0.rain, watered_today, et_mm(d0.tmax, d0.tmin, d0.date, yard), yard.capacity_mm)
        plan["blade"] = fall.blade_in + fall.grow_in.get(iso, 0.0)
        ahead = project_schedule(days[1:], after, since_mow + 1, growth, manuals, yard, **plan)
        for k in (
            "next_water_date", "next_water_mm", "following_water_date", "following_water_mm",
            "next_mow_date", "next_mow_height", "last_mow_of_season", "mows",
        ):
            setattr(sched, k, getattr(ahead, k))
        sched.waters = [[iso, round(watered_today, 2), "logged"]] + ahead.waters
        if fall.cleanup_date == iso:
            sched.last_water_of_season = iso
        elif ahead.last_water_of_season:
            sched.last_water_of_season = ahead.last_water_of_season
    spring = spring_status(highs, lows, pack, yard)
    spring_active = in_spring_season(forecast[0].date)
    spring_out = spring if spring_active else 0
    sched.frost_watch_date = fall.frost_nights[0] if fall.frost_nights else None
    fall_out = fall.as_dict(iso)
    water_kw = {"watered_today_mm": watered_today, "fall": fall_out}
    probe = merge(sched, jev, balance, loc, yard, forecast[0].date, pack=pack, spring=spring_out, **water_kw)
    checklist = evaluate_checklist(
        winter=sched.winter,
        spring=spring_out,
        soil_mm=balance,
        pack_mm=pack,
        forecast=forecast,
        yard=yard,
        days_since_mow=since_mow,
        should_water=probe.lawn_action_items.should_water,
    )
    if not spring_active:
        checklist = [
            {
                **c,
                "status": "wait" if c["status"] == "eligible" else c["status"],
                "reason": (
                    c["reason"] + " · outside Mar–Jun spring window"
                    if c["status"] == "eligible"
                    else c["reason"]
                ),
            }
            for c in checklist
        ]
    report = merge(
        sched, jev, balance, loc, yard, forecast[0].date, pack=pack, spring=spring_out, checklist=checklist, **water_kw
    )
    ran_at = now_cst()
    report.feed = {
        **report.feed,
        "watered_today_mm": round(watered_today, 2),
        "watered_today_minutes": yard.scheduled_water_minutes.get(iso, 0.0),
        "soil_now_mm": round(min(yard.capacity_mm, balance + watered_today), 2),
        "next_water_mm": round(sched.next_water_mm, 2),
        "next_water_minutes": minutes_for(sched.next_water_mm, yard),
        "following_water_mm": round(sched.following_water_mm, 2),
        "following_water_minutes": minutes_for(sched.following_water_mm, yard),
        "next_mow_height": sched.next_mow_height,
        "growth_rate_in_day": yard.growth_rate_in_day,
        "mowed_today": iso in (yard.mow_log or {}),
    }
    record_ledger(ledger_entry(report, ran_at))
    rows = record_rain(rain_by_day(history, om, iso, ran_at))
    report.previous_run = rows[1] if len(rows) > 1 else None
    report.feed = {
        **report.feed,
        "ran_at": ran_at,
        "ledger_count": len(rows),
        "snowpack_mm": report.snowpack_mm,
        "winter_phase": report.winter_phase,
        "spring_phase": report.spring_phase,
    }
    (ROOT / "lawn_state.json").write_text(report.model_dump_json(indent=2))
    publish()
    return report


def main() -> None:
    print(run(refresh=True).model_dump_json(indent=2))


if __name__ == "__main__":
    main()
