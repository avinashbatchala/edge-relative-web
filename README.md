# Edge Relative — Groww chart & scanner POC

A small local FastAPI + Vue 3/TypeScript application. Groww is the sole runtime market-data provider. There is **no demo mode, synthetic runtime feed, or database**. Missing credentials produce an explicit setup state and HTTP 503, never sample prices.

## Start locally

Requires Python 3.11+ (3.12 recommended). Node 22.18+ is needed to edit/build the frontend or run its tests. The archive includes the compiled frontend, so Node is optional for simply running it.

1. Extract the archive and open a terminal in `edge-relative-web`.
2. Copy `.env.example` to `.env`, then fill in `GROWW_API_KEY` and `GROWW_API_SECRET`, or `GROWW_ACCESS_TOKEN`. Complete Groww's required key approval and ensure historical/live data access is enabled for your account. Keep this file local.
3. Run `bash run.sh`. The first run creates a virtual environment and installs backend dependencies.
4. Open **http://127.0.0.1:8000** and click **Fetch / refresh**. Instrument names resolve against Groww's master on the first fetch and are saved to JSON.

On Windows, use WSL for the script or run manually:

```bash
python -m venv .venv
# Activate .venv using your shell's activation command
python -m pip install -r backend/requirements.txt
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --workers 1 --env-file .env
```

Use one worker. The service is intended for one local user and binds to loopback; it does not implement public-server authentication.

## Workspace

- Unified scanner with All / Bullish / Bearish / Mixed / Unavailable filters and symbol search.
- Optional market, sector and volume conditions; classification explains its reasons.
- Click a symbol to open synchronized multi-pane charts: candles and EMA 8/21, volume, rolling RRS, relative volume momentum, relative volatility expansion, market state and sector strength.
- Select benchmarks and change RRS lookback, volume smoothing and volatility ATR length from Settings. Apply on the next fetch.
- Chart pane visibility, crosshair inspection, zoom, replay, CSV export, and fetch diagnostics.
- Live stock LTP and index value feed using pinned SDK 1.5.0; prices are explicitly provisional. OHLCV and scanner values are confirmed by historical candle reconciliation after five-minute completion with a publication grace period.
- Historical replay shows only the chosen data prefix. Indicators are calculated causally in Python, not recomputed differently in the browser.

The volatility study reproduces the supplied script's **relative volatility expansion**. It is not DD02's **relative volume expansion (RVE)**. A price index has no traded volume, so the volume study uses the selected traded proxy; NIFTYBEES is initially configured. No proprietary 1OP formula is claimed.

## Instruments & configuration

`config/instruments.json` initially enables TCS, HDFCBANK and SUNPHARMA plus their sector benchmarks, NIFTY 50 and NIFTYBEES. These are real instrument configuration entries, not demo data. Edit the catalog to change the universe (up to 20 stocks). `sector` identifies another enabled catalog symbol. `groww_symbol` and `exchange_token` are resolved against the current Groww master; do not guess exchange tokens. If a name is ambiguous or unavailable, use its exact Groww symbol and sync again. A failed sector fetch leaves sector values unavailable; a failed volume-proxy fetch leaves volume momentum unavailable while preserving price studies.

`config/scanner.json` sets default benchmarks, indicator parameters, live-feed enablement and publication grace. HTTP-selected settings are retained in memory for live reconciliations. Raw Groww historical candle responses are cached in `data/candles` only when the requested chunk is fully historical. Cache keys include identity, range and interval. Today's ranges are fetched again to reconcile prices/volume. Deleting the cache is safe. No credentials are cached.

## Contracts, boundaries & tests

- `contracts/behavior.md`: timing, units, nullable quality, directional rules, live/replay behavior and UI language.
- `contracts/openapi.json`: generated HTTP contracts, also available at `/openapi.json` and `/docs`.
- `contracts/websocket.schema.json`: status, provisional quote and confirmed snapshot events with schema version, sequence and UTC event time.
- `frontend/src/generated-api.ts`: generated TypeScript contract types. Browser code handles presentation; provider, normalization, indicators and classification stay in Python.
- `backend/app/indicators.py`: existing ThinkScript port with Wilder smoothing, lagged true range, pivot confirmation and prior-session daily context.
- `provider.py`, `feed.py`, `scanner.py`, `service.py`, `main.py`: broker I/O, blocking feed worker, pure directional rules, orchestration, transport.
- Behavior tests were written before the service implementation. Fixtures and the earlier notebook's deterministic generator are confined to `backend/tests`; application code never imports them.

```bash
python -m pip install -r backend/requirements-dev.txt
PYTHONPATH=backend python -m pytest backend/tests -q
npm ci --prefix frontend
npm run test --prefix frontend
npm run build --prefix frontend
PYTHONPATH=backend python backend/export_contracts.py
cd frontend
npx openapi-typescript ../contracts/openapi.json -o src/generated-api.ts
```

For frontend development, run the API on port 8000 and `npm run dev --prefix frontend`. Vite proxies HTTP and WebSocket traffic to the backend. Changes to the instrument catalog require restarting. The sync action refreshes Groww identities for the loaded catalog; JSON structural edits are validated at startup.

## Verification and limits

Local validation: 19 backend tests (including 40 earlier notebook mathematical checks), two frontend unit tests, WebSocket schema checks, TypeScript checking and production compilation. SDK method signatures and feed payload structure were checked against the installed 1.5.0 wheel. Real Groww authentication, account entitlements, continuous live reconnection, and visual browser verification have not been tested here. No credentials were supplied.

Regular NSE 09:15–15:30 IST sessions only. Special sessions, an authoritative holiday calendar, split/dividend adjustments and precise Thinkorswim prefetch/warmup parity are not implemented. Missing observations remain missing; they are never forward-filled into indicator inputs. Scanner labels are directional observations, **not strategy-qualified trade plans**. The app has no order placement or execution simulation.

The future backtester can reuse the pure calculations and scanner on as-of history prefixes. Transaction costs, slippage, positions, trade lifecycle and performance metrics remain future work. This Python POC does not replace the production Java/PostgreSQL design.

SDK references used: Groww Python [authentication](https://groww.in/trade-api/docs/python-sdk), [historical candles](https://groww.in/trade-api/docs/python-sdk/backtesting), [feed](https://groww.in/trade-api/docs/python-sdk/feed), and [instruments](https://groww.in/trade-api/docs/python-sdk/instruments). Charts use [TradingView Lightweight Charts](https://tradingview.github.io/lightweight-charts/), with attribution in the UI.
