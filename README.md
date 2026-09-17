# Grass Optimizer

Daily watering and mowing schedule for a west-facing Martensville, SK yard (Scotts Quick Thick Shade & Sun). Code owns water balance and Saskatchewan winter steps; [Jev](https://docs.typesafe.ai) judges growth, rain, and freeze.

Live on Tailscale only: [grass.austinbakanec.com](https://grass.austinbakanec.com) (same bind as sniper/pp — not on the public internet).

Runs 7am / 12pm / 4pm **America/Regina** (Saskatchewan CST, no DST). Each run appends a newest-first ledger. Change knobs on the page (or in `yard.json`). Never mow on a watering day — cut the dry day before.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # TYPESAFE_API_KEY + WEATHERAPI_KEY
.venv/bin/python -m lawn
```

No API keys belong in this repo. Keys live in `.env` locally and GitHub Actions secrets in CI.
