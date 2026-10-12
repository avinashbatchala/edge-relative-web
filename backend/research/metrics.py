"""Direction evaluation; correlated calls are clustered by market date."""

import numpy as np
import pandas as pd


def nonoverlap(data, signs, bars):
    active = data.copy()
    active["prediction"] = np.asarray(signs, dtype=int)
    active = active[active.prediction != 0].sort_values(["symbol", "decision_time"])
    selected, ends = [], {}
    for index, row in active.iterrows():
        key = (row.symbol, row.date)
        if row.position >= ends.get(key, -1):
            selected.append(index)
            ends[key] = row.position + bars
    return active.loc[selected]


def day_interval(data, values, seed=20261012, block=1):
    frame = pd.DataFrame(
        {"day": data.date.to_numpy(), "value": np.asarray(values, dtype=float)}
    )
    days = frame.groupby("day").value.agg(["sum", "count"])
    if len(days) < 2:
        return None
    random = np.random.default_rng(seed)
    block = min(block, len(days))
    starts = random.integers(0, len(days), size=(2000, int(np.ceil(len(days) / block))))
    choices = ((starts[:, :, None] + np.arange(block)) % len(days)).reshape(2000, -1)[
        :, : len(days)
    ]
    estimates = days["sum"].to_numpy()[choices].sum(axis=1) / days["count"].to_numpy()[
        choices
    ].sum(axis=1)
    return [float(value) for value in np.quantile(estimates, [0.025, 0.975])]


def score(data, signs, bars=6, cost=10, intervals=False):
    calls = nonoverlap(data, signs, bars)
    state_coverage = float(np.count_nonzero(signs) / len(data)) if len(data) else 0
    report = {
        "predictions": len(calls),
        "eligible_rows": len(data),
        "actionable_bar_coverage": state_coverage,
        "sectors": int(calls.sector.nunique()),
        "stocks": int(calls.symbol.nunique()),
        "days": int(calls.date.nunique()),
    }
    if calls.empty:
        return report
    signed = calls.return_bp * calls.prediction
    correct = (signed > 0).astype(float)
    majority_correct = (calls.return_bp * calls.majority_direction > 0).astype(float)
    momentum_correct = (calls.return_bp * calls.momentum_direction > 0).astype(float)
    net = signed - cost
    report.update(
        {
            "accuracy": float(correct.mean()),
            "material_precision": float((signed > 10).mean()),
            "mean_gross_bp": float(signed.mean()),
            "mean_net_bp": float(net.mean()),
            "bullish_predictions": int((calls.prediction == 1).sum()),
            "bearish_predictions": int((calls.prediction == -1).sum()),
            "bullish_accuracy": (
                float(correct[calls.prediction == 1].mean())
                if (calls.prediction == 1).any()
                else None
            ),
            "bearish_accuracy": (
                float(correct[calls.prediction == -1].mean())
                if (calls.prediction == -1).any()
                else None
            ),
            "majority_accuracy_same_entries": float(majority_correct.mean()),
            "momentum_accuracy_same_entries": float(momentum_correct.mean()),
            "net_bp_at_costs": {
                str(fee): float(signed.mean() - fee) for fee in [0, 5, 10, 20]
            },
        }
    )
    calls = calls.assign(correct=correct, net_bp=net)
    report["by_sector"] = {
        name: {
            "predictions": len(part),
            "accuracy": float(part.correct.mean()),
            "mean_net_bp": float(part.net_bp.mean()),
        }
        for name, part in calls.groupby("sector")
    }
    report["by_month"] = {
        name: {
            "predictions": len(part),
            "accuracy": float(part.correct.mean()),
            "mean_net_bp": float(part.net_bp.mean()),
        }
        for name, part in calls.groupby(calls.date.str[:7])
    }
    if intervals:
        report["accuracy_day_bootstrap_95_ci"] = day_interval(calls, correct)
        report["net_bp_day_bootstrap_95_ci"] = day_interval(calls, net)
        report["accuracy_excess_vs_majority_day_bootstrap_95_ci"] = day_interval(
            calls, correct - majority_correct
        )
        report["accuracy_excess_vs_momentum_day_bootstrap_95_ci"] = day_interval(
            calls, correct - momentum_correct
        )
        report["net_bp_5day_block_bootstrap_95_ci"] = day_interval(calls, net, block=5)
        report["accuracy_excess_vs_majority_5day_block_bootstrap_95_ci"] = day_interval(
            calls, correct - majority_correct, block=5
        )
    return report
