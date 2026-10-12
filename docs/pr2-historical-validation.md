# PR #2 historical validation

Validated on October 12, 2026, using the configured backend access token and
Groww SDK 1.5.0. PR #2 was already merged; this follow-up starts from main's
merge commit `c06ebb4`.

Only `GET /v1/historical/candles` was used for broker operations, with five-minute
and official Daily intervals. No instrument sync, live feed, quote, order,
position, or trading API was called. Requests and failure reports omit tokens,
authorization headers, and SDK exception messages.

## Actual broker results

The requested interval was September 22, 09:15 IST through October 12, 15:30
IST. TCS's configured `nse_cas` analysis window keeps 09:15–15:10 candle start
times; the 15:10 candle ends at 15:15. The raw TCS response contained 1,070 rows:
77 noncontinuous rows were excluded, leaving 993 valid continuous candles over
14 observed sessions. The aligned chart and CSV contain 1,008 slots, including
15 missing candles. October 2 was absent from all four intraday sources;
the application did not invent a session or gap for that unobserved date.

| Source | Unresolved September 29 candle starts (IST) | Missing bars |
| --- | --- | ---: |
| TCS | 14:00–15:10, every five minutes | 15 |
| NIFTY 50 | 14:05–15:10, every five minutes | 14 |
| NIFTY IT | 14:05–15:10, every five minutes | 14 |
| NIFTYBEES source history | 14:00–15:25, every five minutes | 18 |

Both targeted retry requests for each source returned zero candles. **No natural
outage gaps recovered.** TCS's other 13 observed sessions were complete. The
unresolved prices stay null in the chart, calculation inputs, CSV, and ZIP;
there is no interpolation or manufactured closing price. NIFTYBEES retains its
own cash-session source window, while TCS comparison outputs use the shared
earlier CAS analysis close.

## Recovery and cache validation

A controlled test removed three otherwise available TCS candles from a
disposable copy of the historical cache: September 28 at 10:00, 10:05, and 10:10
IST. The targeted historical request returned four rows (including the endpoint
overlap); the application restored exactly the three missing candles using
actual Groww OHLCV and preserved the existing fourth candle. A subsequent fetch
reused the persisted repairs. These deliberately removed cache rows are
**separate from the real September 29 outage**, whose 15 gaps remained null.

A repeat full scan reused all five baseline cache entries (four intraday
sources and Daily benchmark history). It issued only eight bounded requests
for the still-missing outage ranges. Complete historical ranges were not fetched
again. Normalized TCS data was identical across scans.

## Behavior and export checks

- Scanner and chart agree on candle time, close, current/prior RRS, volume
  momentum, relative volatility, sector state/RRS, and market regime.
- All 1,008 CSV rows match chart OHLCV and oscillator values, including nulls.
- ZIP result CSV bytes match the CSV endpoint; normalized TCS inputs preserve
  all 15 missing prices. All 16 manifest file hashes verify.
- No dependency fetch failures were recorded. The feed remained disabled.

## Bugs fixed

PR #2 rejected fully quarantined OHLC before attempting recovery, and rejected
auction-only responses before peers could establish an absent continuous
session. Empty responses lost the cache metadata needed to persist later peer
repairs. The intraday provider now retains unusable/empty frames and their
diagnostics/cache metadata for the existing bounded recovery path. Strict
parser callers, malformed/conflicting candle rejection, daily parsing, session
rules, and retry limits retain their existing behavior.

Three new regression tests fail against the original PR #2 implementation and
pass after the fix. Seven new test cases cover all-invalid recovery,
empty/auction-only peer recovery, persistence, conflicting duplicates, and
end-to-end benchmark scanner/export/cache behavior. The full backend suite
passes **54 tests**. The existing frontend suite passes **20 tests**, and
TypeScript checking plus the production build pass.

## Reproduce

From the repository root with the existing environment token binding:

```bash
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q
PYTHONPATH=backend .venv/bin/python backend/validate_history.py
```

The opt-in validator creates an isolated configuration/cache and sanitized
report under ignored `data/historical-validation/<UTC run timestamp>/`. It
does not alter the application catalog or existing cache. It captures initial
versus recovered gaps, request ranges/counts, CSV, ZIP, and the controlled cache
test. Actual historical results may change if Groww backfills the outage later.
The committed [JSON evidence](pr2-historical-validation.json) records this run;
generated market-data files remain local and are not committed.
