# Winter snowpack + spring durability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Track winter snowpack→melt soil moisture and show a formula-first spring checklist with weather gates, without requiring Jev.

**Architecture:** Extend `lawn/rules.py` with a daily moisture step (soil + snowpack), spring phase/height ladder, and pure checklist gates; wire through `daily.py` into `lawn_state.json` and the existing Tailscale UI. Jev off unless `JEV_ENABLED=1`.

**Tech Stack:** Python 3.12+, pydantic, unittest, existing OWM One Call weather adapter, static `index.html`.

**Spec:** `docs/superpowers/specs/2026-10-02-winter-spring-durability-design.md`

## Global Constraints

- Daily resolution only (no hourly melt).
- Keep JSON key `current_water_balance_mm` for soil; add `snowpack_mm`.
- Checklist v1: `wait` | `eligible` | `skip` suggestions only (no done-logging).
- Jev default off; must not override formula water/mow/height/checklist.
- Irrigation always goes to soil, never snowpack.
- Winter lockdown (phase ≥ 3) wins over spring ladder.
- TDD: failing test before production code for each behavior.
- Commits after each task.

## File map

| File | Role |
|---|---|
| `lawn/rules.py` | `melt_cap`, `step_moisture`, `replay_moisture`, `growth_from_highs`, `spring_status`, `season_height`, checklist helpers stay out |
| `lawn/checklist.py` | NEW — `evaluate_checklist(...)` → list of `{id,status,reason}` |
| `lawn/models.py` | Yard knobs (`melt_factor_mm_per_c`, spring thresholds, checklist flags); report fields |
| `lawn/jev.py` | Unchanged API; only called when enabled |
| `lawn/daily.py` | Load pack, replay moisture, formula growth, checklist, optional Jev |
| `tests/test_moisture.py` | NEW |
| `tests/test_season.py` | NEW |
| `tests/test_checklist.py` | NEW |
| `index.html` | Snowpack meter, phase chip, checklist panel |

---

### Task 1: Snowpack + soil day step

**Files:**
- Modify: `lawn/models.py` (Yard: `melt_factor_mm_per_c: float = 2.0`)
- Modify: `lawn/rules.py`
- Create: `tests/test_moisture.py`

**Produces:**
- `melt_cap(tmax: float, yard: Yard) -> float`
- `step_moisture(soil: float, pack: float, day: Day, manual: float, yard: Yard) -> tuple[float, float]`
- `replay_moisture(days, start_soil, start_pack, manuals, yard, since=None) -> tuple[float, float]`

- [ ] **Step 1: Failing tests**

```python
# tests/test_moisture.py
class MeltTests(unittest.TestCase):
    def test_freezing_day_precip_goes_to_pack_not_soil(self): ...
    def test_warm_day_melts_pack_into_soil_capped(self): ...
    def test_irrigation_always_hits_soil(self): ...
```

- [ ] **Step 2: Run — expect FAIL (missing symbols)**
- [ ] **Step 3: Implement `melt_cap`, `step_moisture`, `replay_moisture` per spec**
- [ ] **Step 4: Tests PASS**
- [ ] **Step 5: Commit** `feat: add snowpack soil moisture step`

---

### Task 2: Formula growth + Jev gate

**Files:**
- Modify: `lawn/rules.py` — `growth_from_highs(highs: list[float]) -> Literal["low","medium","high"]`
- Modify: `lawn/daily.py` — skip `ask_jev` unless `os.environ.get("JEV_ENABLED") == "1"`; stub jev dict with formula growth
- Test: `tests/test_season.py` (growth cases)

**Produces:** formula growth used for `project_schedule` / report when Jev off.

- [ ] **Step 1: Failing growth-band tests**
- [ ] **Step 2: Implement + wire daily.py**
- [ ] **Step 3: unittest discover PASS (no Typesafe call when JEV off)**
- [ ] **Step 4: Commit** `feat: formula growth with Jev opt-in`

---

### Task 3: Spring phases + season height

**Files:**
- Modify: `lawn/models.py` — spring threshold knobs on Yard
- Modify: `lawn/rules.py` — `spring_status`, `season_height(winter, spring, yard)`, extend `heights` or add `spring_heights`
- Test: `tests/test_season.py`

**Produces:**
- `spring_status(highs, lows, pack_mm, yard) -> int`  # 0..3
- `season_height(winter: int, spring: int, yard) -> float`  # lockdown wins

- [ ] **Step 1: Tests for S0–S2 gates and winter precedence**
- [ ] **Step 2: Implement**
- [ ] **Step 3: PASS + commit** `feat: spring phase height ladder`

---

### Task 4: Spring checklist gates

**Files:**
- Create: `lawn/checklist.py`
- Create: `tests/test_checklist.py`
- Modify: `lawn/models.py` — optional `checklist_enabled: dict[str, bool]` default all True

**Produces:** `evaluate_checklist(*, winter, spring, soil_mm, pack_mm, forecast, yard, days_since_mow, should_water) -> list[dict]`

Items: `blowout_ready`, `first_water`, `first_mow`, `raise_height`, `first_fertilizer`, `overseed`, `aerate`.

- [ ] **Step 1: Fixture tests for wait/eligible/skip per item**
- [ ] **Step 2: Implement pure functions**
- [ ] **Step 3: PASS + commit** `feat: weather-gated spring checklist`

---

### Task 5: Wire daily run + UI + publish

**Files:**
- Modify: `lawn/daily.py` — load/save `snowpack_mm`; use `replay_moisture`; attach `checklist`, `season` fields to report/feed
- Modify: `lawn/models.py` — DailyReport fields: `snowpack_mm`, `checklist`, feed extras
- Modify: `index.html` — snowpack line, phase chip, checklist table
- Modify: `yard.json` — melt_factor default if missing (pydantic default OK)

- [ ] **Step 1: Extend report model + daily.run**
- [ ] **Step 2: UI paint checklist + pack**
- [ ] **Step 3: `python -m unittest discover -s tests` PASS**
- [ ] **Step 4: `JEV_ENABLED=0 python -m lawn` succeeds; publish**
- [ ] **Step 5: Commit** `feat: surface snowpack and spring checklist on grass UI`

---

## Spec coverage

| Spec requirement | Task |
|---|---|
| Snowpack / melt / irrigation→soil | 1 |
| Persist snowpack_mm | 5 |
| Formula growth, Jev off | 2 |
| Spring phases + height up | 3 |
| Checklist wait/eligible/skip | 4–5 |
| Daily only, no hourly | all |
| UI panel | 5 |
