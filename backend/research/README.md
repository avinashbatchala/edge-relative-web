# Multi-sector intraday direction research

Opt-in historical research for the requested 15–60 minute prediction horizon.
The application continues to use its existing relative-strength scanner. The
selected research candidate did not pass the predeclared deployment gates.

The fixed universe has 20 liquid stocks across IT, banks, pharma, auto, FMCG,
and metals. Only Groww's historical-candles API is used. No instrument sync,
live-feed, quote, order, position, or trading API is called; no exchange tokens
are invented. Historical responses validate the requested broker symbols.
The selected stocks use the repository's versioned CAS analysis profile,
including the older cash-session window before August 3, 2026. Indices use the
same analysis window without claiming they are auction-traded.

## Reproduce the saved experiment

From `/workspace/edge-relative-web`, with Python 3.11+ and an already injected
`GROWW_ACCESS_TOKEN`:

```bash
.venv/bin/python -m pip install -r backend/requirements-research.txt
PYTHONPATH=backend .venv/bin/python -m research.fetch
PYTHONWARNINGS=ignore PYTHONPATH=backend .venv/bin/python -m research.dataset
OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 PYTHONPATH=backend .venv/bin/python -m research.tune tune
OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 PYTHONPATH=backend .venv/bin/python -m research.tune evaluate
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests backend/research/tests -q
```

The token belongs in secure environment settings, never chat, code, logs, or
`VITE_` variables. SDK error messages are suppressed because they may contain
credentials. Source files, weights, datasets, and reports are kept separately:

- `data/multisector-research/cache/`: original historical response cache.
- Per-instrument `.pkl` files: trusted, locally generated normalized OHLCV.
- `development.pkl`, `selection.pkl`, `test.pkl`: separate chronological sets.
- `dataset_audit.json`: source quality and 80 actual-data causal-prefix checks.
- `tuning_search.json`: all 45 candidates and 78 threshold combinations.
- `frozen.json`, `frozen_model.joblib`: chosen model/threshold, training provenance,
  and hashes of the design, model, source, and test data.
- `final_test.json`, `test_predictions.csv`: fixed candidate and baseline results.

These files are ignored by Git. Load pickle/joblib files only when generated
locally by the trusted research code. Optional research dependencies are
separate from application dependencies.

## Evaluation contract

The primary target is the absolute stock return over 30 minutes, entering at
the next candle open after a signal is available. Fifteen and sixty minutes
are secondary outcome checks of the same frozen 30-minute model. Labels stay
within the continuous session and reject any missing intervening stock OHLC;
prices and outage gaps are never filled. The first 30 minutes are excluded.
Ten basis points define both a material move and the illustrative round-trip
cost assumption. Returns are per prediction, not simulated portfolio profits.

September 2025 supplies indicator warmup. October 2025–May 2026 is development;
February–May expanding folds assess stability. June–July selects parameters
and threshold. August 3–October 12 is final testing. Six stocks, one per sector,
never participate in fitting or threshold selection. TCS is excluded from the
primary final aggregate because earlier research examined its recent outcomes.

Candidate rules vary RRS length, directional confirmation, EMA agreement, and
strength. Learned candidates use regularized three-class logistic regression,
boosted classification, and boosted return regression. Every feature is causal
and scale-normalized; ticker IDs and future outcomes are not model inputs.
Classifiers can abstain when the noise/flat class is strongest or the action
score is too low. Action scores are not claims of calibrated live probabilities.

Training uses fixed, non-overlapping decision times. Test scoring thins each
stock's active predictions to avoid overlapping outcome windows. Confidence
intervals resample entire market dates, with five-day block checks to account
for serial dependence and correlated stocks. Baselines include RRS, momentum,
EMA direction, and a stock/sector majority direction learned before the test.

`tune` never loads final-test rows. It freezes the selected model before
`evaluate` loads the test. Once `final_test.json` exists, retuning the same
experiment is refused. Do not delete that guard to optimize observed test
results. A new experiment needs a new versioned design, output directory, and
untouched test data; this snapshot's dates and grid are intentionally fixed.

The selected candidate must pass selection stability, sample size, directional
coverage, sector diversity, paired baseline advantage, positive net-return
confidence bounds, and never-trained-stock checks before production adoption.
The recorded experiment failed those gates. See
[`docs/multisector-signal-validation.md`](../../docs/multisector-signal-validation.md).
