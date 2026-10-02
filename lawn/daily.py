from __future__ import annotations

import json
import os
import shutil
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from lawn.checklist import evaluate_checklist
from lawn.jev import ask_jev
from lawn.models import DailyReport, LawnActionItems, ScheduleOut, Yard
from lawn.rules import (
    cycle_mm,
    days_since_mow,
    growth_from_highs,
    in_spring_season,
    manuals_mm,
    project_schedule,
    replay_moisture,
    season_end,
    season_height,
    spring_status,
)
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
    freeze = 1.0 if any(d.tmin <= 0 for d in forecast[:7]) else 0.0
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
) -> str:
    place = f"{loc.get('name')}, {loc.get('region')}"
    last_water = sched.last_water_of_season or "not yet dated"
    last_mow = sched.last_mow_of_season or "not yet dated"
    follow = sched.following_water_date or "unscheduled"
    watch = sched.frost_watch_date or "none in window"
    return (
        f"{place}. Soil {balance:.1f} mm + snowpack {pack:.1f} mm "
        f"(profile {y.capacity_mm:g} mm). Growth {growth}. "
        f"Next water {sched.next_water_date} "
        f"({cycle_mm(y)} mm / {y.cycle_minutes:g} min @ {y.gpm:g} GPM); "
        f"water again {follow}. Last deep soak {last_water}. "
        f"Next mow {sched.next_mow_date}; last winter cut {last_mow}. "
        f"Frost watch {watch}. Winter {sched.winter} / spring {spring}. "
        f"Rain-in-48h {jev['significant_rain_24_48h']:.2f}, freeze {jev['freeze_blowout_now']:.2f}."
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
) -> DailyReport:
    y = yard or Yard()
    shutdown = sched.winter >= 3 or jev["freeze_blowout_now"] >= YES
    skip_water = jev["rain_covers_watering"] >= YES and not shutdown
    should_water = (sched.should_water or shutdown) and not skip_water
    should_mow = (sched.should_mow or jev["should_mow_now"] >= YES) and not should_water
    spring_active = in_spring_season(as_of)
    if spring_active and spring == 0 and sched.winter <= 1 and not shutdown:
        should_mow = False  # dormant/thaw: don't cut
    target = y.winter_soak_mm if shutdown else (sched.target_water_mm if should_water else 0.0)
    spring_for_height = spring if spring_active else (2 if sched.winter == 0 else 0)
    height = season_height(sched.winter, spring_for_height, y)
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
        reasoning_summary=reason(balance, pack, jev["growth"], sched, loc, jev, y, spring),
        schedule=ScheduleOut(
            next_water_date=sched.next_water_date,
            following_water_date=sched.following_water_date,
            next_mow_date=sched.next_mow_date,
            last_water_of_season=sched.last_water_of_season,
            last_mow_of_season=sched.last_mow_of_season,
            frost_watch_date=sched.frost_watch_date,
        ),
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
    key = os.environ.get("OPENWEATHER_API_KEY") or os.environ["WEATHERAPI_KEY"]
    loc, history, forecast = fetch_weather(key, yard)
    today = date.fromisoformat(forecast[0].date)
    manuals = manuals_mm(yard)
    saved_as_of, saved_bal, saved_pack = load_saved()
    if saved_as_of is not None and saved_bal is not None:
        balance, pack = replay_moisture(
            history, start_soil=saved_bal, start_pack=saved_pack, manuals=manuals, yard=yard, since=saved_as_of
        )
    else:
        balance, pack = replay_moisture(
            history,
            start_soil=yard.prior_balance_mm,
            start_pack=yard.prior_snowpack_mm,
            manuals=manuals,
            yard=yard,
        )
    since_mow = days_since_mow(today, yard.last_mow_date)
    highs = [d.tmax for d in forecast[:7]]
    lows = [d.tmin for d in forecast[:7]]
    growth = growth_from_highs(highs)
    if os.environ.get("JEV_ENABLED") == "1":
        jev = ask_jev(yard, loc, history, forecast, balance, since_mow)
        growth = jev["growth"]
    else:
        jev = formula_signals(forecast, growth, yard)
    sched = project_schedule(forecast, balance, since_mow, growth, manuals, yard)
    spring = spring_status(highs, lows, pack, yard)
    spring_active = in_spring_season(forecast[0].date)
    spring_out = spring if spring_active else 0
    if not sched.last_water_of_season:
        last_mow, last_water = season_end(forecast + fetch_horizon(key, yard, today))
        sched.last_mow_of_season = sched.last_mow_of_season or last_mow
        sched.last_water_of_season = last_water
    sched.frost_watch_date = next((d.date for d in forecast if d.tmin <= 1), None)
    probe = merge(sched, jev, balance, loc, yard, forecast[0].date, pack=pack, spring=spring_out)
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
        sched, jev, balance, loc, yard, forecast[0].date, pack=pack, spring=spring_out, checklist=checklist
    )
    ran_at = now_cst()
    rows = record_ledger(ledger_entry(report, ran_at))
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
    print(run().model_dump_json(indent=2))


if __name__ == "__main__":
    main()
