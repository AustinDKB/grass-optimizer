from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

from lawn.jev import ask_jev
from lawn.models import DailyReport, LawnActionItems, ScheduleOut, Yard
from lawn.rules import CYCLE_MM, project_schedule, replay, season_end
from lawn.weather import fetch_horizon, fetch_weather

ROOT = Path(__file__).resolve().parent.parent
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


def reason(balance: float, growth: str, sched, loc: dict, jev: dict) -> str:
    place = f"{loc.get('name')}, {loc.get('region')}"
    last_water = sched.last_water_of_season or "not yet dated"
    last_mow = sched.last_mow_of_season or "not yet dated"
    follow = sched.following_water_date or "unscheduled"
    watch = sched.frost_watch_date or "none in 14 days"
    return (
        f"{place}. Soil water balance {balance:.1f} mm of a 25 mm profile. "
        f"Growth {growth}. Next water {sched.next_water_date} ({CYCLE_MM} mm / 50 min); "
        f"water again {follow}. Last deep soak {last_water}. "
        f"Next mow {sched.next_mow_date}; last winter cut {last_mow}. "
        f"Frost watch {watch}. Winter phase {sched.winter} "
        f"(0 summer / 1 slowing / 2 final cut / 3 lockdown). "
        f"Jev rain-in-48h {jev['significant_rain_24_48h']:.2f}, freeze {jev['freeze_blowout_now']:.2f}."
    )


def merge(sched, jev: dict, balance: float, loc: dict) -> DailyReport:
    shutdown = sched.winter >= 3 or jev["freeze_blowout_now"] >= YES
    skip_water = jev["rain_covers_watering"] >= YES and not shutdown
    should_water = (sched.should_water or shutdown) and not skip_water
    should_mow = sched.should_mow or jev["should_mow_now"] >= YES
    target = WINTER if shutdown else (sched.target_water_mm if should_water else 0.0)
    return DailyReport(
        current_water_balance_mm=round(balance, 2),
        estimated_growth_rate=jev["growth"],
        lawn_action_items=LawnActionItems(
            should_water=should_water,
            target_water_amount_mm=round(target, 2),
            should_mow=should_mow,
            recommended_mower_height_inches=2.25 if shutdown else sched.mower_height,
            is_winter_shutdown_triggered=shutdown,
        ),
        reasoning_summary=reason(balance, jev["growth"], sched, loc, jev),
        schedule=ScheduleOut(
            next_water_date=sched.next_water_date,
            following_water_date=sched.following_water_date,
            next_mow_date=sched.next_mow_date,
            last_water_of_season=sched.last_water_of_season,
            last_mow_of_season=sched.last_mow_of_season,
            frost_watch_date=sched.frost_watch_date,
        ),
        jev=jev,
    )


WINTER = 25.0


def run() -> DailyReport:
    load_env()
    yard = Yard()
    loc, history, forecast = fetch_weather(os.environ["WEATHERAPI_KEY"], yard)
    today = date.fromisoformat(forecast[0].date)
    tomorrow = (today + timedelta(days=1)).isoformat()
    balance = replay(history)
    days_since = 0
    jev = ask_jev(yard, loc, history, forecast, balance, days_since)
    sched = project_schedule(
        forecast, balance, days_since, jev["growth"], {tomorrow: CYCLE_MM}
    )
    if not sched.last_water_of_season:
        last_mow, last_water = season_end(
            forecast + fetch_horizon(os.environ["WEATHERAPI_KEY"], yard, today)
        )
        sched.last_mow_of_season = sched.last_mow_of_season or last_mow
        sched.last_water_of_season = last_water
    sched.frost_watch_date = next((d.date for d in forecast if d.tmin <= 1), None)
    report = merge(sched, jev, balance, loc)
    (ROOT / "lawn_state.json").write_text(report.model_dump_json(indent=2))
    return report


def main() -> None:
    print(run().model_dump_json(indent=2))


if __name__ == "__main__":
    main()
