# Edge Relative - US market workspace

FastAPI + Vue application for US equities using Schwabdev. Prices are USD; charts and sessions use America/New_York with daylight saving time. No synthetic runtime prices or order execution.

## Setup

1. Run `./run.ps1` on Windows or `./run.sh` on Unix to install dependencies and build.
2. Set `SCHWAB_APP_KEY`, `SCHWAB_APP_SECRET`, and your registered `SCHWAB_CALLBACK_URL` in `.env` (see `.env.example`).
3. Run `.venv/Scripts/python.exe backend/auth_schwab.py` in an interactive terminal (Unix: `.venv/bin/python`). Complete Schwab browser authorization and paste the callback URL when prompted.
4. Restart the app and open http://127.0.0.1:8000. Select Fetch / refresh.

Tokens are stored in `SCHWAB_TOKENS_DB` (default `data/schwab/tokens.db`), under the ignored data directory. Keep this file private. The SDK refreshes tokens automatically; repeat authorization when refresh access expires. API requests return a setup error when authorization is required.

## Universe and sessions

`config/instruments.json` seeds AAPL, MSFT, NVDA, JPM, JNJ, SPY, XLK, XLF and XLV. Stocks use sector ETFs as benchmarks. SPY supplies both price and traded-volume benchmarks. Seeds configure real symbols; prices require Schwab access.

Only the `us_regular` session is supported: 09:30-16:00 Eastern, 78 five-minute candles per full day. Premarket and after-hours bars are excluded. Observed trading dates supply the session calendar; authoritative holidays, early closes, and corporate-action adjustments are not implemented. Missing candles remain missing and bounded history retries attempt recovery.

Live mode polls Schwab quotes every five seconds. Quotes are provisional; scanner calculations use completed candles. Historical availability depends on Schwab entitlements and retention. The UI allows up to 90 calendar days; unavailable data remains unavailable.

Historical market-data responses are cached under `data/candles`. Delete this cache safely to force a reload. Cache identities include US symbols and session policy. Live validation status is recorded in `docs/`.

## Development

Backend (PowerShell): `$env:PYTHONPATH="backend"; .venv/Scripts/python.exe -m pytest backend/tests`.
Frontend: `npm test --prefix frontend` and `npm run build --prefix frontend`.
Regenerate schemas with `python backend/export_contracts.py`, then `npx openapi-typescript contracts/openapi.json -o frontend/src/generated-api.ts`.
Opt-in authenticated history smoke check: `python backend/validate_history.py`.

SDK documentation and setup: https://github.com/tylerebowers/Schwabdev
