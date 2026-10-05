from __future__ import annotations

from lawn.models import Yard


def actions_from_yard(yard: Yard) -> list[dict]:
    rows = [
        {"date": d, "action": "water", "amount": float(m)}
        for d, m in yard.scheduled_water_minutes.items()
    ]
    for d, h in yard.mow_log.items():
        rows.append({"date": d, "action": "mow", "amount": float(h)})
    for d, h in (yard.height_log or {}).items():
        rows.append({"date": d, "action": "measure", "amount": float(h)})
    rows.sort(key=lambda r: (r["date"], r["action"]))
    return rows


def yard_patch_from_actions(actions: list[dict]) -> dict:
    scheduled: dict[str, float] = {}
    mow_log: dict[str, float] = {}
    height_log: dict[str, float] = {}
    for raw in actions:
        action = str(raw.get("action", "")).lower()
        date = str(raw.get("date", "")).strip()
        if not date:
            continue
        amount = float(raw.get("amount") or 0)
        if action == "water":
            scheduled[date] = amount
        elif action == "mow":
            mow_log[date] = amount
        elif action == "measure":
            height_log[date] = amount
    patch: dict = {
        "scheduled_water_minutes": scheduled,
        "mow_log": mow_log,
        "height_log": height_log,
    }
    if mow_log:
        latest = max(mow_log)
        patch["last_mow_date"] = latest
        patch["mower_height_inches"] = mow_log[latest]
    return patch
