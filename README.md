# Grass Optimizer

Daily watering and mowing schedule for a west-facing Martensville, SK yard (Scotts Quick Thick Shade & Sun). Code owns water balance and Saskatchewan winter steps; [Jev](https://docs.typesafe.ai) judges growth, rain, and freeze.

Live on Tailscale only: [grass.austinbakanec.com](https://grass.austinbakanec.com) (same bind as sniper/pp — not on the public internet).

Edit `yard.json` for live-feed knobs: `cycle_minutes`, `gpm`, `sqft`, last mow date, scheduled water minutes, soil `capacity_mm` / `trigger_mm`, `kc`, and mower deck. The daily snapshot copies those into `lawn_state.json` so the page does not hardcode them.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # TYPESAFE_API_KEY + WEATHERAPI_KEY
.venv/bin/python -m lawn
```

No API keys belong in this repo. Keys live in `.env` locally and GitHub Actions secrets in CI.
