# Grass Optimizer: winter moisture + spring checklist (formula-first)

Date: 2026-10-02  
Repo: `gress-optmizer`  
Status: approved for spec; implementation awaits plan approval

## Goal

Run the same daily grass system through winter and into spring for **maximum turf durability** on a west-facing Martensville, SK Quick Thick lawn:

1. Track weather all winter and estimate **realistic soil moisture after snowmelt**.
2. Show a **full optional spring checklist** with weather gates (`wait` / `eligible` / `skip`).
3. Prefer **deterministic formulas** over Jev; Jev is optional and off by default.

Out of scope for this design: hourly melt simulation, a second parallel physics engine, fertilizer product brands, paid lab soil tests as hard gates.

## Decisions locked

| Decision | Choice |
|---|---|
| Architecture | Extend the existing daily engine (Approach 1) |
| Moisture model | Daily precip → snowpack (SWE) when frozen; melt into soil when warm |
| Temporal resolution | Daily OpenWeather `day_summary` / One Call daily — **not** hourly |
| Checklist v1 | Weather-gated **suggestions only** (no “done on” logging yet) |
| Jev | **Off by default**; formulas own growth, phase, water, mow |
| Growth proxy | Temperature bands (replace Jev growth score) |

## Current system (baseline)

Today the stack already owns:

- Soil water balance (ET − rain − logged irrigation, capacity/trigger)
- Mow timing (interval by growth, never mow on a water day)
- Winter **shutdown** phases from forecast highs/lows → cut height
- Ledger + `yard.json` knobs + Tailscale UI

Gaps vs this goal:

- Precip in cold weather is treated like liquid rain (no snowpack deferral)
- No spring phase ladder (height goes down for winter, never back up for green-up)
- No spring cultural checklist
- Jev overlaps formulas and is not required for durability decisions
- Ledger hole risk if the timer stops in winter (melt estimate then has to be backfilled)

## Architecture

Keep one daily run (`python -m lawn`). Extend state and rules; do not add a second service.

```
OWM daily / day_summary
        │
        ▼
┌───────────────────┐
│  weather → Day[]  │  (already)
└─────────┬─────────┘
          ▼
┌───────────────────┐
│ snowpack + soil   │  NEW: winter accounting in rules/replay
│ water balance     │
└─────────┬─────────┘
          ▼
┌───────────────────┐
│ season phase      │  EXTEND: winter 0–3 + spring 0–3 (or unified season ladder)
│ height / water /  │
│ mow               │
└─────────┬─────────┘
          ▼
┌───────────────────┐
│ spring checklist  │  NEW: pure functions → wait|eligible|skip + reason
└─────────┬─────────┘
          ▼
 lawn_state.json + UI + ledger
```

Jev, if ever re-enabled via env flag, may only annotate; it must not override formula water/mow/height/checklist gates.

## Winter moisture model

### State

Persist in `lawn_state.json` (and optionally mirror key fields in ledger rows):

- `soil_mm` — same meaning as today’s `current_water_balance_mm` (rename in UI copy only if cheap; keep JSON key for compatibility unless a migration is trivial)
- `snowpack_mm` — snow water equivalent waiting to melt (new)
- `as_of` — unchanged semantics

### Day step (conceptual)

For each history/forecast day with temps and precip `p` (rain + snow liquid equivalent from OWM):

1. If `tmax <= 0`: add `p` to `snowpack_mm` (not soil). ET ≈ 0 when deeply cold (existing ET already collapses in hard cold).
2. Else if `snowpack_mm > 0` and `tmax > 0`: melt `min(snowpack_mm, melt_cap(tmax, tmin))` into soil; add any liquid `p` to soil; apply ET as today.
3. Else (no pack, above freezing): current behavior — `p` and irrigation into soil, minus ET, clamp to `[0, capacity]`.

`melt_cap` v1: simple degree-day style, e.g. `k * max(tmax, 0)` with `k` in `yard.json` (default tuned for prairie; overridable). No hourly.

Irrigation logged in `scheduled_water_minutes` always goes to **soil**, never pack (hose water is liquid).

### Why this is enough

Durability care about **how wet the root zone is after melt**, not the hour melt finishes. Daily max/min + precip already support pack build and multi-day melt pulses. Hourly is explicitly deferred.

### Continuity

The existing 7am/12pm/4pm timer must keep running in winter. If a gap appears, support the same **day_summary backfill** path used for Sep 24–30 so pack/soil can be rebuilt.

## Season phases and cut height

### Winter (existing, keep)

| Phase | Gate (next ~7 days) | Height (current deck snap) |
|---|---|---|
| 0 summer | not cold | 3.5" |
| 1 slowing | highs mostly &lt; 15°C | 3.0" |
| 2 final | highs mostly &lt; 8°C | 2.5" |
| 3 lockdown | any night ≤ 0°C | 2.5" + deep soak / blowout cue |

### Spring (new, durability-oriented)

Spring phases only apply when leaving lockdown / after sustained thaw (e.g. no ≤0°C night in window and highs recovering). Ladder **up** for durability (never scalp early):

| Phase | Gate (sketch) | Height | Intent |
|---|---|---|---|
| S0 dormant/thaw | soil/pack thawing; growth off | no mow (or hold last winter height) | Don’t cut soft/dormant turf |
| S1 green-up | highs mostly ≥ ~10–12°C, growth starting | 3.0" first cuts | Raise from winter short cut gradually |
| S2 established | highs mostly ≥ ~15°C, active growth | 3.5" | Full summer height |
| S3 summer | stable warm | 3.5" | Hand off to existing summer rules |

Exact thresholds live in `yard.json` next to winter knobs so Martensville can be tuned without code edits.

Growth label (mow interval) from formulas, not Jev:

- low: cool band (e.g. mean high &lt; 15°C)
- medium: 15–22°C
- high: &gt; 22°C  

(Same bands Jev’s prompt already described.)

## Spring checklist (optional, gated)

v1 = **suggestions only**. Each item: `status ∈ {wait, eligible, skip}` + short `reason`. No completion dates in v1 (future: log like water/mow).

Suggested catalog (all optional; yard can disable items):

| ID | Item | Eligible when (examples) | Skip when |
|---|---|---|---|
| `blowout_done_check` | Confirm sprinklers ready / lines not frozen | After lockdown clears; tmax consistently &gt; 0 | Mid-summer |
| `first_water` | First light irrigation | Pack gone or negligible; soil below trigger; no soak rain in 48h; past hard freeze window | Soil already wet from melt |
| `first_mow` | First mow of season | S1+; turf dry enough; days since last cut satisfied; not a water day | Still S0 |
| `raise_height` | Step mower up toward 3.5" | After first mow(s); entering S2 | Already at summer height |
| `first_fertilizer` | Light spring feed cue | Soil workable; active green-up; not before sustained thaw | Peak heat / drought stress |
| `overseed` | Overseed window | Cool moist stretch; not lockdown; soil contact possible | Hot dry forecast |
| `aerate` | Aeration window | Soil moist not saturated; growth active; not before thaw | Frozen or mud |

Gates are pure functions of `(phase, soil_mm, snowpack_mm, forecast, yard)`. Checklist does not command hardware; it only advises.

## UI / API

- Show **soil mm**, **snowpack mm**, season phase, and height on the existing page.
- New checklist panel: one row per item with status + reason.
- `lawn_state.json` gains `snowpack_mm`, `season_phase` (or winter+spring fields), `checklist: [{id, status, reason}]`.
- Settings: melt factor + checklist enable flags in `yard.json`; no new microservice.

## Jev policy

- Env `JEV_ENABLED=0` default (or omit key → disabled).
- When disabled: growth from temp bands; freeze/rain/mow from rules only.
- When enabled: Jev scores may appear in the report for curiosity but **must not** flip `should_water`, `should_mow`, height, or checklist status.

## Testing

- Unit: snowpack accrual on freezing days; melt into soil on warm days; soil clamp; irrigation never increases pack.
- Unit: spring phase transitions and height ladder.
- Unit: each checklist item hit `wait` / `eligible` / `skip` with fixture forecasts.
- Unit: Jev disabled path produces a full report without Typesafe calls.
- No dependency on live OWM in unit tests (fixture `Day` lists).

## Rollout

1. Snowpack + soil step in `replay` / daily run; persist pack; UI readouts.
2. Formula growth; Jev off by default.
3. Spring phases + height-up ladder.
4. Checklist gates + UI panel.
5. Keep winter timer + document backfill for gaps.

## Non-goals (explicit)

- Hourly One Call for melt timing
- Parallel SWE model separate from soil balance
- Mandatory checklist completion tracking (v1)
- Replacing OpenWeather with another provider again in this work
