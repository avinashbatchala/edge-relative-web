# Multi-sector signal tuning: actual historical results

**A larger sample and tuning improved the candidate's reported hit rate, but
did not establish a reliable, cost-effective stock-direction predictor.**
The frozen candidate remains an offline research artifact; production scanner
rules were not replaced with an unvalidated model.

## Sample and design

- 20 stocks across six sectors; 408,060 five-minute stock slots, 406,444 usable
  prices, and 274 observed source sessions from September 1, 2025–October 12, 2026.
- 250 evaluated market sessions and 5,000 stock-session pairs from October 1,
  2025. There are 933,066 labeled 15/30/60-minute observations; these are
  correlated observations, not 933,066 independent trials.
- Stocks: TCS, INFY, HCLTECH, WIPRO; HDFCBANK, ICICIBANK, SBIN, AXISBANK;
  SUNPHARMA, CIPLA, DRREDDY; MARUTI, M&M, BAJAJ-AUTO; HINDUNILVR, ITC,
  NESTLEIND; TATASTEEL, JSWSTEEL, HINDALCO.
- All 28 historical sources (stocks, market/sector indices, and volume proxy)
  downloaded successfully. Missing prices and outage gaps stayed missing.
- Twelve months of evaluation use development through May 31, 2026; four
  expanding February–May validation folds; June–July selection; and a reserved
  August 3–October 12 final test of 48 market dates.
- HCLTECH, AXISBANK, DRREDDY, MARUTI, NESTLEIND, and HINDALCO were never used in
  model fitting or threshold selection. TCS is secondary-only in final reporting
  because previous research already examined its recent outcomes.

Only historical-candle APIs were used. Entries are the next candle open after
the signal closes, exits are 15/30/60 minutes later, and labels cannot cross an
overnight boundary or an intervening missing stock candle. The first 30 minutes
are excluded. Next-open fills assume no execution delay. Ten basis points
(0.10%) is an illustrative round-trip cost, with 0/5/10/20 bp sensitivity also
reported. No portfolio, position sizing, orders, or live execution is simulated.

## What was tuned

45 candidates / 78 candidate-threshold combinations were evaluated:

- RRS lookbacks 8/12/20, confirmation 1/2/3 bars, EMA agreement, and minimum
  relative-strength thresholds.
- Regularized three-class logistic regression.
- Boosted direction/noise classifiers and future-return regressors with 7/15/31 leaves.
- Direction/noise action thresholds and return thresholds that allow abstention.

Models have 54 past/current features: stock, sector and market returns, relative
strength/volume/volatility, ATR, EMA distance/slope, candle structure, session
returns/time, own volume, and sector indicators. Ticker identity and future
outcomes are excluded. All 80 actual-data prefix checks pass, and the complete
application/research suite passes 62 tests.

The best adequately sized candidate selected before final testing is a boosted
three-class classifier: seven leaves, 150 iterations, learning rate 0.05,
minimum leaf size 100, L2 regularization 10, action-score threshold 0.45. It
was refitted on 30,867 non-overlapping training observations from 14 stocks
ending July 31. Its selection-window hit rate was 52.03% across 369 calls, but
its gross mean move was only 3.65 bp and it passed zero positive-net development
folds. **None of the 78 combinations passed the predeclared selection gates.**

The candidate was frozen despite that failure for diagnostic testing. No
parameters, thresholds, or production rules were changed after final results.

## Primary final result: 30 minutes

The primary aggregate excludes TCS and contains 19 stocks / 48 reserved dates.
Outcome windows are thinned within each stock, and uncertainty resamples whole
market dates and five-day blocks rather than treating correlated stocks as
independent observations.

| Policy | Non-overlapping calls | Direction hit rate | Mean gross signed move | Mean net at 10 bp cost |
| --- | ---: | ---: | ---: | ---: |
| Frozen tuned candidate | 783 | 54.92% | +2.09 bp | −7.91 bp |
| Current RRS | 8,723 | 48.22% | −0.26 bp | −10.26 bp |
| 15-minute momentum | 9,937 | 48.70% | +0.31 bp | −9.69 bp |
| EMA 8/21 | 10,146 | 49.21% | −0.16 bp | −10.16 bp |
| Training-period majority direction | 10,146 | 51.88% | +1.15 bp | −8.85 bp |

Policies select different timestamps. The higher candidate hit rate does not
by itself prove an improvement at equivalent entries. At the candidate's exact
783 entries, the training-majority baseline scores 51.85% and momentum 46.62%.
The candidate's 95% day-cluster accuracy interval is **49.54–60.85%**. Its paired
advantage over the majority baseline has a five-day-block interval of
**−3.60 to +8.90 percentage points**, which includes no advantage.

Only 2.55% of eligible bars receive a candidate direction, versus RRS's 56.43%.
That is roughly 0.86 non-overlapping calls per stock-session. Its 323 bullish
calls score 51.08%; its 460 bearish calls score 57.61%. Only 41.38% of all calls
move more than 10 bp in the predicted direction. These scores are not calibrated
probabilities of a profitable future trade.

The mean net-return five-day-block interval is **−12.28 to −3.62 bp** at the
10 bp assumption. Even at 5 bp, the mean is −2.91 bp. The candidate fails the
predeclared coverage and baseline-advantage checks as well as the cost checks.

## Transfer to never-trained stocks

The six excluded stocks produce 317 calls at 30 minutes: **53.00% accuracy**,
1.97 bp mean gross move, and **−8.03 bp** after the 10 bp assumption. Their
accuracy interval is 45.90–60.61%; the majority baseline scores 52.37% at the
same entries. Transfer does not establish a robust improvement.

## Sector and horizon breakdown

| Sector | Candidate calls | Accuracy | Mean net at 10 bp |
| --- | ---: | ---: | ---: |
| Auto | 120 | 56.67% | −8.46 bp |
| Banks | 106 | 51.89% | −8.60 bp |
| FMCG | 87 | 52.87% | −8.93 bp |
| IT | 189 | 55.03% | −7.17 bp |
| Metals | 176 | 57.39% | −6.46 bp |
| Pharma | 105 | 53.33% | −9.55 bp |

Every sector's mean net result is negative. August, September, and October are
also negative separately. Fifteen and sixty minutes are secondary outcomes of
the same frozen 30-minute predictor, not separately optimized models:

| Outcome horizon | Calls | Accuracy | Mean net at 10 bp |
| --- | ---: | ---: | ---: |
| 15 minutes | 1,074 | 54.84% | −6.40 bp |
| 30 minutes | 783 | 54.92% | −7.91 bp |
| 60 minutes | 550 | 51.82% | −10.52 bp |

## Decision

The search completed and the selected algorithm is saved, but the goal of a
dependable absolute-direction predictor is **not yet demonstrated**. Adding
more model complexity or increasing the reported hit rate would not fix the
weak economic result or wide baseline-advantage interval. The existing RRS
scanner remains a relative-performance observation tool.

Retain this test as completed evidence. New features or rules need a new
predeclared experiment and untouched data, rather than further optimization
against the now-observed August–October results. Current-stock selection has
survivorship bias; historical candles may be revised/backfilled; point-in-time
live availability and real execution costs remain unverified.

## Reproducibility and artifacts

The optional pipeline and dependency list are in `backend/research/` and
`backend/requirements-research.txt`. See the
[research instructions](../backend/research/README.md) and
[compact JSON evidence](multisector-signal-validation.json).

Full raw/normalized history, search results, hashes, frozen weights, predictions,
and test reports are retained locally under ignored `data/multisector-research/`.
The code refuses to retune after final-test inspection and verifies design,
source, model, and test-data hashes before evaluation. Model weights and broker
market-data files are not committed. No credentials or authorization headers
are stored in evidence.
