# Schwab-only POC behavior v1

Two views: unified scanner and chart workspace. No database. No runtime synthetic data, demo route, or credential fallback. Missing credentials allow the UI to load in a truthful unconfigured state; fetch returns HTTP 503.

The supplied ThinkScript studies are the numerical source of truth for this POC. DD01–05 inform data provenance, dependency alignment, nullable quality, and component boundaries. This experimental Python service is separate from the production Java/PostgreSQL architecture. The directional scanner is an observation, not a strategy-qualified setup or order recommendation. No broker order APIs are called.

## Timing and units
- HTTP request timestamps must contain timezone offsets. Responses use epoch seconds for candles, ISO 8601 UTC for event timestamps, and explicit America/New_York display timezone. Candle timestamps identify the beginning of a five-minute interval.
- Price is USD; volume is shares; oscillators are dimensionless. Market and sector regime codes have explicit mappings in the chart response.
- Scanner evaluates only closed regular US session bars. Data is aligned to five-minute session slots; missing values remain null. Wilder averages reset and rewarm after gaps. Duplicate conflicts fail.
- The five studies are rolling RRS, relative volume momentum, relative **volatility** expansion (distinct from DD02 volume-expansion RVE), market state, sector strength.
- SPY is the price benchmark. Relative volume momentum requires an explicitly configured tradable volume proxy, whose identity is displayed.
- Bullish = RRS > 0 and greater than its immediately preceding completed value. Bearish = RRS < 0 and less than its preceding value. Other ready rows are mixed. Missing stock/market bars or RRS warmup yield unavailable. Optional market/sector/volume filters can downgrade to mixed/unavailable with reasons.
- Freshness is separate from historical validity. Current-session scans must reach the expected completed slot (20-second publication grace); otherwise rows are stale/unavailable. Historical snapshots are marked historical. No artificial holiday calendar is claimed.

## Transport
HTTP: GET health, GET instruments, POST scan, GET charts/{symbol}, GET exports/{symbol}.csv. `/openapi.json` is the authoritative HTTP schema. POST instruments/sync resolves configured names uniquely against Schwab's instrument lookup and atomically saves identities to JSON.
WebSocket: `/api/v1/ws` uses explicit versioned discriminated messages: status, quote, snapshot. Monotonic sequence per service instance; ISO sent_at; no secrets. Quotes are provisional price observations, never confirmed OHLCV. Snapshots contain completed-candle observations. Clients reload on sequence loss/reconnect; slow clients are disconnected rather than silently losing confirmed messages.

## Live behavior
One process, one quote worker. The worker polls Schwab quotes every five seconds and marks unchanged observations stale after 60 seconds. Scheduled history reconciliation runs after completed five-minute boundaries. Quotes never invent volume or modify confirmed candles. Reconnection triggers reconciliation.


## UI language
Dark neutral surfaces, cyan focus, emerald bullish, rose bearish, amber mixed, muted unavailable. Text labels always accompany color. Compact bordered controls, tabular numeric typography, visible benchmark identities, keyboard-operable row buttons, loading/empty/error/stale states. Shared typed API contracts; Python owns calculations. Lightweight Charts attribution stays visible.

## Deliberate scope
JSON catalog/config, file candle cache, in-memory snapshots, HTTP/WebSocket, local single-user runtime. Future backtesting may call the same pure indicator/scanner functions on an as-of prefix; fills, costs, slippage, lifecycle, and metrics are not implemented. Local regular-session handling does not include special sessions/corporate action adjustments. Exact TOS warmup parity and live Schwab validation require external verification.


## Continuous sessions and recoverable gaps

Catalog `session_profile` is `us_regular`: 09:30-16:00 America/New_York, with 78 five-minute slots on a full trading day. The last candle starts at 15:55. Extended hours are excluded; daylight saving time follows New York. Early-close calendars are not implemented.


Only observed source/peer trading dates establish the expected grid. Completed requested slots absent or quarantined in a source are retried in bounded broker calls; they remain null if recovery fails. Valid existing OHLC is preserved; missing traded volume is accepted only with matching OHLC. No index-volume retry, forward fill, fabricated prices, holiday assumption, or changed event formula is introduced. Recovery diagnostics are included in the captured export run.
