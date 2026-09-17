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
    next_mow_date: str | None
    last_water_of_season: str | None
    last_mow_of_season: str | None
    frost_watch_date: str | None = None


class DailyReport(BaseModel):
    current_water_balance_mm: float
    estimated_growth_rate: Literal["low", "medium", "high"]
    lawn_action_items: LawnActionItems
    reasoning_summary: str
    schedule: ScheduleOut
    jev: dict = Field(default_factory=dict)


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
