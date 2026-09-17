from __future__ import annotations

import json
import os
import shutil
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from lawn.jev import ask_jev
from lawn.models import DailyReport, LawnActionItems, ScheduleOut, Yard
from lawn.rules import cycle_mm, days_since_mow, heights, manuals_mm, project_schedule, replay, season_end
from lawn.weather import fetch_horizon, fetch_weather

ROOT = Path(__file__).resolve().parent.parent
PUBLISH = Path("/var/www/grass")
LEDGER = ROOT / "ledger.json"
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
    return Yard.model_validate_json(path.read_text())


def save_yard(data: dict) -> Yard:
    current = load_yard().model_dump()
    current.update({k: v for k, v in data.items() if v is not None})
    yard = Yard.model_validate(current)
    (ROOT / "yard.json").write_text(yard.model_dump_json(indent=2))
    return yard


def load_saved() -> tuple[str | None, float | None]:
    path = ROOT / "lawn_state.json"
    if not path.exists():
        return None, None
    data = json.loads(path.read_text())
    as_of = data.get("as_of")
    bal = data.get("current_water_balance_mm")
    if not as_of or bal is None:
        return None, None
    return str(as_of), float(bal)


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


def reason(balance: float, growth: str, sched, loc: dict, jev: dict, y: Yard) -> str:
    place = f"{loc.get('name')}, {loc.get('region')}"
    last_water = sched.last_water_of_season or "not yet dated"
    last_mow = sched.last_mow_of_season or "not yet dated"
    follow = sched.following_water_date or "unscheduled"
    watch = sched.frost_watch_date or "none in 14 days"
    return (
        f"{place}. Soil water balance {balance:.1f} mm of a {y.capacity_mm:g} mm profile. "
        f"Growth {growth}. Next water {sched.next_water_date} "
        f"({cycle_mm(y)} mm / {y.cycle_minutes:g} min @ {y.gpm:g} GPM); "
        f"water again {follow}. Last deep soak {last_water}. "
        f"Next mow {sched.next_mow_date}; last winter cut {last_mow}. "
        f"Frost watch {watch}. Winter phase {sched.winter} "
        f"(0 summer / 1 slowing / 2 final cut / 3 lockdown). "
        f"Jev rain-in-48h {jev['significant_rain_24_48h']:.2f}, freeze {jev['freeze_blowout_now']:.2f}."
    )


def merge(sched, jev: dict, balance: float, loc: dict, yard: Yard | None = None, as_of: str | None = None) -> DailyReport:
    y = yard or Yard()
    shutdown = sched.winter >= 3 or jev["freeze_blowout_now"] >= YES
    skip_water = jev["rain_covers_watering"] >= YES and not shutdown
    should_water = (sched.should_water or shutdown) and not skip_water
    should_mow = (sched.should_mow or jev["should_mow_now"] >= YES) and not should_water
    target = y.winter_soak_mm if shutdown else (sched.target_water_mm if should_water else 0.0)
    height = heights(y)[3] if shutdown else sched.mower_height
    when = as_of or ""
    return DailyReport(
        current_water_balance_mm=round(balance, 2),
        estimated_growth_rate=jev["growth"],
        lawn_action_items=LawnActionItems(
            should_water=should_water,
            target_water_amount_mm=round(target, 2),
            should_mow=should_mow,
            recommended_mower_height_inches=height,
            is_winter_shutdown_triggered=shutdown,
        ),
        reasoning_summary=reason(balance, jev["growth"], sched, loc, jev, y),
        schedule=ScheduleOut(
            next_water_date=sched.next_water_date,
            following_water_date=sched.following_water_date,
            next_mow_date=sched.next_mow_date,
            last_water_of_season=sched.last_water_of_season,
            last_mow_of_season=sched.last_mow_of_season,
            frost_watch_date=sched.frost_watch_date,
        ),
        jev=jev,
        as_of=as_of,
        feed=feed_of(y, when, target),
    )


def now_cst() -> str:
    return datetime.now(CST).isoformat(timespec="minutes")


def record_ledger(entry: dict, path: Path | None = None) -> list[dict]:
    dest = path or LEDGER
    rows = json.loads(dest.read_text()) if dest.exists() else []
    rows.insert(0, entry)
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


def run() -> DailyReport:
    load_env()
    yard = load_yard()
    loc, history, forecast = fetch_weather(os.environ["WEATHERAPI_KEY"], yard)
    today = date.fromisoformat(forecast[0].date)
    manuals = manuals_mm(yard)
    saved_as_of, saved_bal = load_saved()
    if saved_as_of is not None and saved_bal is not None:
        balance = replay(history, start=saved_bal, manuals=manuals, yard=yard, since=saved_as_of)
    else:
        balance = replay(history, start=yard.prior_balance_mm, manuals=manuals, yard=yard)
    since_mow = days_since_mow(today, yard.last_mow_date)
    jev = ask_jev(yard, loc, history, forecast, balance, since_mow)
    sched = project_schedule(forecast, balance, since_mow, jev["growth"], manuals, yard)
    if not sched.last_water_of_season:
        last_mow, last_water = season_end(
            forecast + fetch_horizon(os.environ["WEATHERAPI_KEY"], yard, today)
        )
        sched.last_mow_of_season = sched.last_mow_of_season or last_mow
        sched.last_water_of_season = last_water
    sched.frost_watch_date = next((d.date for d in forecast if d.tmin <= 1), None)
    report = merge(sched, jev, balance, loc, yard, forecast[0].date)
    ran_at = now_cst()
    rows = record_ledger(ledger_entry(report, ran_at))
    report.previous_run = rows[1] if len(rows) > 1 else None
    report.feed = {**report.feed, "ran_at": ran_at, "ledger_count": len(rows)}
    (ROOT / "lawn_state.json").write_text(report.model_dump_json(indent=2))
    publish()
    return report
    load_env()
    yard = load_yard()
    loc, history, forecast = fetch_weather(os.environ["WEATHERAPI_KEY"], yard)
    today = date.fromisoformat(forecast[0].date)
    manuals = manuals_mm(yard)
    saved_as_of, saved_bal = load_saved()
    if saved_as_of is not None and saved_bal is not None:
        balance = replay(history, start=saved_bal, manuals=manuals, yard=yard, since=saved_as_of)
    else:
        balance = replay(history, start=yard.prior_balance_mm, manuals=manuals, yard=yard)
    since_mow = days_since_mow(today, yard.last_mow_date)
    jev = ask_jev(yard, loc, history, forecast, balance, since_mow)
    sched = project_schedule(forecast, balance, since_mow, jev["growth"], manuals, yard)
    if not sched.last_water_of_season:
        last_mow, last_water = season_end(
            forecast + fetch_horizon(os.environ["WEATHERAPI_KEY"], yard, today)
        )
        sched.last_mow_of_season = sched.last_mow_of_season or last_mow
        sched.last_water_of_season = last_water
    sched.frost_watch_date = next((d.date for d in forecast if d.tmin <= 1), None)
    report = merge(sched, jev, balance, loc, yard, forecast[0].date)
    (ROOT / "lawn_state.json").write_text(report.model_dump_json(indent=2))
    return report


def main() -> None:
    print(run().model_dump_json(indent=2))


if __name__ == "__main__":
    main()
