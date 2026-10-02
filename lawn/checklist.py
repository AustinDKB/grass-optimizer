from __future__ import annotations

from lawn.models import Day, Yard

CATALOG = (
    "blowout_ready",
    "first_water",
    "first_mow",
    "raise_height",
    "first_fertilizer",
    "overseed",
    "aerate",
)


def _enabled(yard: Yard, item_id: str) -> bool:
    flags = yard.checklist_enabled or {}
    return flags.get(item_id, True)


def _item(item_id: str, status: str, reason: str) -> dict:
    return {"id": item_id, "status": status, "reason": reason}


def evaluate_checklist(
    *,
    winter: int,
    spring: int,
    soil_mm: float,
    pack_mm: float,
    forecast: list[Day],
    yard: Yard,
    days_since_mow: int,
    should_water: bool,
) -> list[dict]:
    highs = [d.tmax for d in forecast[:7]]
    lows = [d.tmin for d in forecast[:7]]
    rain48 = sum(d.rain for d in forecast[:3])
    out: list[dict] = []

    for item_id in CATALOG:
        if not _enabled(yard, item_id):
            out.append(_item(item_id, "skip", "disabled in yard settings"))
            continue

        if item_id == "blowout_ready":
            if winter >= 3 or (lows and min(lows) <= 0):
                out.append(_item(item_id, "wait", "still in freeze / lockdown window"))
            elif spring >= 1:
                out.append(_item(item_id, "eligible", "thaw holding — check lines before first soak"))
            else:
                out.append(_item(item_id, "wait", "waiting for sustained thaw"))

        elif item_id == "first_water":
            if pack_mm > yard.spring_pack_clear_mm:
                out.append(_item(item_id, "wait", "snowpack still melting into soil"))
            elif soil_mm >= yard.trigger_mm:
                out.append(_item(item_id, "skip", "soil already at/above trigger after melt"))
            elif rain48 >= yard.major_rain_mm:
                out.append(_item(item_id, "wait", "soaking rain in next 48h"))
            elif winter >= 3:
                out.append(_item(item_id, "wait", "lockdown — deep soak/blowout rules apply instead"))
            elif spring >= 1:
                out.append(_item(item_id, "eligible", "pack clear and soil below trigger"))
            else:
                out.append(_item(item_id, "wait", "not in green-up yet"))

        elif item_id == "first_mow":
            if spring < 1 or winter >= 2:
                out.append(_item(item_id, "wait", "turf not in green-up / still winter-short"))
            elif should_water:
                out.append(_item(item_id, "wait", "watering day — cut the dry day before"))
            elif days_since_mow <= 0:
                out.append(_item(item_id, "skip", "already mowed today"))
            else:
                out.append(_item(item_id, "eligible", "green-up and dry — first cuts at spring height"))

        elif item_id == "raise_height":
            if spring >= 2:
                out.append(_item(item_id, "eligible", "step deck up to summer 3.5 in"))
            elif spring == 1:
                out.append(_item(item_id, "wait", "stay near 3.0 in through early green-up"))
            else:
                out.append(_item(item_id, "wait", "not in spring ladder yet"))

        elif item_id == "first_fertilizer":
            if winter >= 3 or spring < 1:
                out.append(_item(item_id, "wait", "wait for green-up after thaw"))
            elif spring >= 1 and pack_mm <= yard.spring_pack_clear_mm:
                out.append(_item(item_id, "eligible", "soil workable and growth starting"))
            else:
                out.append(_item(item_id, "wait", "pack still present"))

        elif item_id == "overseed":
            if winter >= 2 or spring < 1:
                out.append(_item(item_id, "wait", "too cold / dormant for seed"))
            elif highs and sum(1 for h in highs if h > 25) >= 3:
                out.append(_item(item_id, "skip", "too hot for reliable germination"))
            else:
                out.append(_item(item_id, "eligible", "cool moist green-up window"))

        elif item_id == "aerate":
            if winter >= 3 or spring < 1:
                out.append(_item(item_id, "wait", "soil frozen or dormant"))
            elif soil_mm >= yard.capacity_mm * 0.9:
                out.append(_item(item_id, "wait", "soil too wet / saturated"))
            elif soil_mm < yard.trigger_mm * 0.5:
                out.append(_item(item_id, "wait", "soil too dry for clean cores"))
            else:
                out.append(_item(item_id, "eligible", "moist not saturated — good aerate window"))

    return out
