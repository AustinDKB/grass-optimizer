# Grass Optimizer

Daily watering and mowing schedule for a west-facing Martensville, SK yard (Scotts Quick Thick Shade & Sun). Code owns water balance and Saskatchewan winter steps; [Jev](https://docs.typesafe.ai) judges growth, rain, and freeze.

Live: [grass.austinbakanec.com](https://grass.austinbakanec.com)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # TYPESAFE_API_KEY + WEATHERAPI_KEY
.venv/bin/python -m lawn
```

No API keys belong in this repo. Keys live in `.env` locally and GitHub Actions secrets in CI.
