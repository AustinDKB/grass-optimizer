from typesafe_sdk import Choice, Noul, Score, TypeSafeClient

from lawn.models import Day, Yard
from lawn.rules import HEIGHT, winter_status


def questions() -> dict:
    return {
        "growth": Score(
            instructions="How fast will Scotts Quick Thick Shade & Sun (fescue/KBG/rye mix) grow this week at `yard` given `history` and `forecast`?",
            criteria=[
                "Low: highs near or below 15C, little vertical growth after a recent cut.",
                "Medium: highs 16-22C, typical fall clipping volume.",
                "High: highs above 22C with moisture, rapid internodal growth.",
            ],
        ),
        "significant_rain_24_48h": Noul(
            instructions="Does `forecast` show a soaking rain (~8mm+) in the next 24-48 hours, not a trace?",
        ),
        "should_mow_now": Noul(
            instructions=(
                "Mow today while dry, including slightly early to beat rain or watering? "
                "Never if `lawn.days_since_mow` is 0."
            ),
        ),
        "rain_covers_watering": Noul(
            instructions="Will rain in 48 hours refill the soil enough to skip manual watering, ignoring winter shutdown?",
        ),
        "freeze_blowout_now": Noul(
            instructions="Do `forecast` lows hit 0C or below in 7 nights, requiring a 25mm soak and sprinkler blowout now?",
        ),
        "mower_regime": Choice(
            instructions="Which SK winter mowing height regime applies to `forecast` highs?",
            criteria={
                "summer": "Highs not consistently below 15C. Keep 3.5 inches.",
                "slowing": "Highs consistently below 15C but not 8C. Cut at 3.0 inches (deck snap from 2.75).",
                "final": "Highs consistently below 8C or freeze imminent. Final cut 2.5 inches.",
            },
        ),
    }


def growth_label(score: float) -> str:
    if score < 0.5:
        return "low"
    if score < 1.5:
        return "medium"
    return "high"


def ask_jev(yard: Yard, location: dict, history: list[Day], forecast: list[Day], balance_mm: float, days_since_mow: int) -> dict:
    highs = [d.tmax for d in forecast[:7]]
    lows = [d.tmin for d in forecast[:7]]
    state = {
        "yard": yard.model_dump(),
        "location": {k: location.get(k) for k in ("name", "region", "lat", "lon")},
        "policy": {
            "water_balance_mm": round(balance_mm, 2),
            "mow_before_watering": True,
            "major_rain_mm": 8,
            "winter_phase_code": winter_status(highs, lows),
            "mower_height_inches_by_phase": list(HEIGHT),
        },
        "lawn": {"days_since_mow": days_since_mow, "current_mower_height_inches": yard.mower_height_inches},
        "history": [d.model_dump() for d in history],
        "forecast": [d.model_dump() for d in forecast],
    }
    with TypeSafeClient(model="jev-latest") as client:
        res = client.system_one(state=state, questions=questions())
    g = res.scores["growth"]
    return {
        "growth": growth_label(g.score),
        "growth_score": g.score,
        "growth_confidence": g.confidence,
        "significant_rain_24_48h": res.nouls["significant_rain_24_48h"].noul,
        "should_mow_now": res.nouls["should_mow_now"].noul,
        "rain_covers_watering": res.nouls["rain_covers_watering"].noul,
        "freeze_blowout_now": res.nouls["freeze_blowout_now"].noul,
        "mower_regime": res.choices["mower_regime"].choice,
        "mower_regime_confidence": res.choices["mower_regime"].confidence,
        "model": res.model,
    }
