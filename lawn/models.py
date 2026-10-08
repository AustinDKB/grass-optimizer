from pydantic import BaseModel, Field
from typing import Literal


class Day(BaseModel):
    date: str
    tmax: float
    tmin: float
    rain: float

    @property
    def month(self) -> int:
        return int(self.date[5:7])


class LawnActionItems(BaseModel):
    should_water: bool
    target_water_amount_mm: float
    should_mow: bool
    recommended_mower_height_inches: float
    is_winter_shutdown_triggered: bool


class ScheduleOut(BaseModel):
    next_water_date: str | None
    following_water_date: str | None = None
    next_water_mm: float = 0.0
    following_water_mm: float = 0.0
    next_mow_date: str | None
    next_mow_height: float | None = None
    last_water_of_season: str | None
    last_mow_of_season: str | None
    frost_watch_date: str | None = None
    final_soak_mm: float = 0.0
    mows: list = Field(default_factory=list)
    waters: list = Field(default_factory=list)


class DailyReport(BaseModel):
    current_water_balance_mm: float
    snowpack_mm: float = 0.0
    estimated_growth_rate: Literal["low", "medium", "high"]
    lawn_action_items: LawnActionItems
    reasoning_summary: str
    schedule: ScheduleOut
    winter_phase: int = 0
    spring_phase: int = 0
    checklist: list[dict] = Field(default_factory=list)
    jev: dict = Field(default_factory=dict)
    as_of: str | None = None
    feed: dict = Field(default_factory=dict)
    fall: dict = Field(default_factory=dict)
    previous_run: dict | None = None


class Yard(BaseModel):
    address: str = "702B 1st Avenue North, Martensville, SK"
    lat: float = 52.2897
    lon: float = -106.6667
    grass: str = "Scotts Turf Builder Quick Thick Shade & Sun"
    facing: str = "west"
    light: str = "morning shade, afternoon sun"
    sqft: float = 1000
    gpm: float = 4
    cycle_minutes: float = 50
    mower_height_inches: float = 3.0
    mower_max_inches: float = 4.0
    mower_deck: list[float] = Field(default_factory=lambda: [1.25, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0])
    height_targets_in: list[float] = Field(default_factory=lambda: [3.5, 2.75, 2.25, 2.25])
    capacity_mm: float = 25
    trigger_mm: float = 10
    major_rain_mm: float = 8
    melt_factor_mm_per_c: float = 2.0
    melt_soak_fraction: float = 0.4  # share of snow melt that soaks in; the rest runs off frozen ground
    spring_green_high_c: float = 10.0
    spring_summer_high_c: float = 15.0
    spring_pack_clear_mm: float = 5.0
    spring_heights_in: list[float] = Field(default_factory=lambda: [2.5, 3.0, 3.5, 3.5])
    checklist_enabled: dict[str, bool] = Field(default_factory=dict)
    kc: float = 0.95
    et_factor: float = 1.0
    mow_interval_days: dict[str, int] = Field(default_factory=lambda: {"low": 10, "medium": 7, "high": 5})
    last_mow_date: str = "2026-09-17"
    mow_log: dict[str, float] = Field(default_factory=dict)
    height_log: dict[str, float] = Field(default_factory=dict)  # measured blade height, inches
    growth_rate_in_day: float = 0.15  # blade growth at 20 °C mean air and warm soil
    hose_ice_in: float = 0.25  # ice in the hose that forces the cleanup
    hose_margin_c: float = 2.0  # ground-level air runs colder than the 2 m forecast on clear nights
    hose_risk_pct: float = 20  # climate fallback: date by which this % of past years froze
    dormant_soil_c: float = 5.0  # soil (6 cm) daily mean below this ...
    dormant_days: int = 5  # ... for this many days in a row = growth stopped, all off
    frost_c: float = 1.0  # low at or below this = frost warning
    scheduled_water_minutes: dict[str, float] = Field(default_factory=lambda: {"2026-09-18": 50})
    prior_balance_mm: float = 15
    prior_snowpack_mm: float = 0.0
