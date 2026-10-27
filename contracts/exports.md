# Diagnostic export contract — version 2.0

Exports preserve the complete **loaded scan**, independent of zoom, pane visibility, selected study, and replay position. No broker fetch or calculation is triggered during export. No provisional LTP quotes are exported. Data is sourced exclusively from the current captured Schwab scan; deterministic input providers exist only in tests.

## Endpoints

- `GET /api/v1/exports/{symbol}.csv`: one stock, every loaded completed interval and every available feature.
- `GET /api/v1/exports/run.zip`: all successful stock results and the input data needed to inspect/recalculate them.
- Both accept optional `run_id`. The chart response exposes this identifier. A replaced run returns HTTP 409 with a refresh instruction, preventing an export from silently differing from the displayed chart.
- HTTP 404 indicates no loaded history or an unknown stock. Error bodies are JSON, never downloadable CSV files.
- Success returns the appropriate CSV/ZIP media type, attachment filename, `Cache-Control: no-store`, and `X-Export-Run-Id`.

Run capture holds one coherent set of results, inputs, request, settings and snapshot. A background scan may replace the current run, but an in-progress export retains its captured run. There is no accumulating run database. Failed history reconciliation leaves the last successfully captured run exportable; its capture-time quality is preserved, not relabeled as current freshness.

## CSV representation

UTF-8 with BOM for spreadsheet compatibility. Standard quoted CSV with CRLF row endings. Null values are empty fields. Booleans are `true` or `false`. Actual zero remains zero. Nonfinite values are never emitted as `NaN`/`Infinity`. Numeric precision is retained without display rounding. Text that could be interpreted as a spreadsheet formula is apostrophe-prefixed; negative numbers remain numeric.

Each row includes:

- Export version, run ID, symbol, provider, request range, scan generation time, interval, session profile/policy/phase and units.
- Beginning-of-candle epoch seconds, UTC/ET timestamps with offsets, ET session date, end-of-candle UTC time.
- Stock open/high/low/close/volume and availability flags.
- Price benchmark, volume benchmark and sector benchmark identities and their aligned OHLCV.
- RRS, RRV and relative **volatility** expansion, all their correlations and original bull/bear event flags.
- Immediately preceding values, availability, rising/falling, direction, strength and weakness observations for each oscillator.
- Sector RRS, fast/slow smoothers, confirmed RRS, state, counts, and new strength/weakness events.
- Market regime, phase, bias, efficiency, swings and previous levels, readiness, Daily/M5 flags, confirmation counts, confirmed bull/bear conditions, new bull/bear/dislocation events, entry status and readable labels.
- Price EMA 8 and EMA 21.
- Per-row price/RRS availability and capture-time scanner quality/direction/reasons.
- Exact indicator parameters as quoted JSON.

Known feature columns remain present even when a dependency is absent. Their values are null. Additional future `ChartPoint.features` keys are automatically included.

`*_strength` means positive and rising relative to the **immediately preceding aligned bar**; `*_weakness` means negative and falling. They are null when either required value is absent. These observational states differ from the original `*_bull_event`/`*_bear_event`, which deliberately retain the supplied study's one-bar-lagged transition timing. No trade fills are inferred.

`market_dislocation` is the ongoing ready regime-4 state. `market_new_dislocation` is the existing transition flag. Sector states and transition flags preserve the Python engine's confirmation and opening-blackout rules.

`row_quality` covers price and RRS availability, not the validity of all studies. `snapshot_*` fields repeat the latest scanner context at **run capture**, including its filter decisions; they are not historical per-row scanner evaluations. Exported original false event flags remain false during warmup; use readiness/availability fields to interpret them.

## ZIP contents

- `results/*.csv`: expanded per-stock result files.
- `inputs/*_5m.csv`: normalized stock/index/proxy/sector OHLCV in each source's continuous session window. Reindex these inputs to the result CSV's shared session profile to reproduce a mixed-profile comparison. Gaps and quarantined prices remain missing. Tradeless index volume stays null.
- `inputs/benchmark_daily.csv`: the completed benchmark Daily input history used by the market-state engine, including its fetched warmup range; omitted if that dependency failed.
- `scanner_snapshot.json`: capture-time scanner results.
- `diagnostics.json`: missing input counts, parser quarantine reason counts/sample rows, fetch failures, separate noncontinuous-row counts, and bounded gap-recovery attempts/results.
- `data_dictionary.json`: field interpretations, null/boolean encoding, state mappings, and signal timing.
- `engine/*.py`: indicator, scanner, orchestration, export, session policy, provider and contract source used by the running process.
- `manifest.json`: request, parameters, instrument identities, row counts, input-file mapping, generation time, numerical runtime versions, code hashes, and SHA-256 of every other included file.

No credentials, environment variables, account tokens, or live quote snapshots are included. Benchmark/source exports are normalized inputs, not a claim that raw ticks or complete original broker responses have been retained.

## Interpretation boundaries

RRV is relative volume momentum, not time-of-day RVOL. Relative volatility expansion is based on underlying ATR, not option IV or DD02's volume-expansion RVE. These remain experimental directional observations rather than strategy-qualified setups.

The bundle supports checking alignment, warmup, missingness, formula continuity and the exact Python implementation. It does not establish Thinkorswim prefetch parity or introduce corporate-action adjustments, special-session calendars, trade execution, or backtesting. Algorithm tuning should evaluate separate/out-of-sample periods rather than optimizing only a supplied export.


## Continuous session policy

`session_policy_version=us-regular-v1`; `session_profile=us_regular` and `session_phase=continuous`. Full trading days have 78 five-minute slots, 09:30 through 15:55 in America/New_York. Exported local timestamps include the applicable daylight saving offset.


Missing expected slots remain null unless Schwab supplies a validated repair. Recovery diagnostics distinguish verified price/volume repairs from remaining holes and do not retain broker exceptions or credentials. Parser quarantine counts describe the original response; current missingness counts describe the post-recovery input. Noncontinuous/auction rows do not count as missing or invalid continuous candles. Daily benchmark history remains the completed official Daily input, including its official closing auction price where applicable.
