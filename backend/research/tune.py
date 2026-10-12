"""Tune without loading final-test data, freeze, then evaluate in a separate step."""

import argparse
import hashlib
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits
from research.fetch import ROOT
from research.universe import COLD_STOCKS
from research.models import (
    candidates,
    make_model,
    raw_prediction,
    action,
    thresholds,
    majority_maps,
    with_majority,
    fixed_clock_sample,
)
from research.metrics import score, nonoverlap

DESIGN_PATH = Path(__file__).with_name("design.json")
DESIGN = json.loads(DESIGN_PATH.read_text())


def source_hashes():
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in Path(__file__).parent.glob("*.py")
    }


def primary(data):
    return data[
        (data.horizon_minutes == 30) & ~data.symbol.isin(COLD_STOCKS)
    ].reset_index(drop=True)


def fit(model, config, data, names):
    if config["family"] == "rule":
        return model
    target = (
        data.return_bp if config["family"] == "boosted_regressor" else data.class_label
    )
    with threadpool_limits(limits=2):
        model.fit(data[names], target)
    return model


def predict(model, config, data, names):
    with threadpool_limits(limits=2):
        return raw_prediction(model, config, data[names])


def enough(metrics):
    return (
        metrics["predictions"] >= DESIGN["selection_min_predictions"]
        and metrics["actionable_bar_coverage"] >= DESIGN["selection_min_coverage"]
        and metrics["sectors"] >= DESIGN["selection_min_sectors"]
    )


def tune():
    if (ROOT / "final_test.json").exists():
        raise RuntimeError(
            "The final test was already inspected; a new tuning run needs a new untouched test design"
        )
    # Test data is deliberately not loaded by this function.
    development_all = pd.read_pickle(ROOT / "development.pkl")
    selection_all = pd.read_pickle(ROOT / "selection.pkl")
    development = fixed_clock_sample(primary(development_all))
    selection = fixed_clock_sample(primary(selection_all))
    names = json.loads((ROOT / "dataset_audit.json").read_text())["features"]
    choices = []
    for number, config in enumerate(candidates(), 1):
        print(
            f"[{number}/{len(candidates())}] Walk-forward tuning: {config}", flush=True
        )
        fold_scores = {str(t): [] for t in thresholds(config)}
        for month in DESIGN["walk_forward_validation_months"]:
            left = pd.Timestamp(month + "-01")
            right = left + pd.offsets.MonthBegin(1)
            train = development[development.date < left.strftime("%Y-%m-%d")]
            valid = development[
                (development.date >= left.strftime("%Y-%m-%d"))
                & (development.date < right.strftime("%Y-%m-%d"))
            ]
            mapping = majority_maps(train)
            valid = with_majority(valid, mapping)
            model = fit(make_model(config), config, train, names)
            raw = predict(model, config, valid, names)
            for threshold in thresholds(config):
                metrics = score(valid, action(raw, config, threshold))
                fold_scores[str(threshold)].append({"month": month, **metrics})
        model = fit(make_model(config), config, development, names)
        valid = with_majority(selection, majority_maps(development))
        raw = predict(model, config, valid, names)
        for threshold in thresholds(config):
            metrics = score(valid, action(raw, config, threshold))
            folds = fold_scores[str(threshold)]
            positives = sum(
                f.get("mean_net_bp", -np.inf) > 0 and f["predictions"] >= 50
                for f in folds
            )
            choices.append(
                {
                    "config": config,
                    "threshold": threshold,
                    "selection": metrics,
                    "folds": folds,
                    "positive_development_folds": positives,
                    "selection_passed": bool(
                        enough(metrics)
                        and metrics.get("mean_net_bp", -np.inf) > 0
                        and positives >= 3
                    ),
                }
            )
        (ROOT / "tuning_search.json").write_text(json.dumps(choices, indent=2))
    passed = [c for c in choices if c["selection_passed"]]
    acceptable_size = [c for c in choices if enough(c["selection"])]
    pool = passed or acceptable_size
    if not pool:
        raise RuntimeError(
            "No candidate meets minimum sample/coverage requirements; do not use the test to invent a threshold"
        )
    chosen = max(pool, key=lambda c: c["selection"].get("mean_net_bp", -np.inf))
    print(
        "Frozen candidate:",
        chosen["config"],
        "threshold",
        chosen["threshold"],
        "selection gate",
        chosen["selection_passed"],
        flush=True,
    )
    all_before_test = pd.concat([development_all, selection_all], ignore_index=True)
    training = fixed_clock_sample(primary(all_before_test))
    model = fit(make_model(chosen["config"]), chosen["config"], training, names)
    joblib.dump(model, ROOT / "frozen_model.joblib")
    mapping = {
        str(h): majority_maps(
            fixed_clock_sample(
                all_before_test[
                    (all_before_test.horizon_minutes == h)
                    & ~all_before_test.symbol.isin(COLD_STOCKS)
                ],
                h,
            )
        )
        for h in [15, 30, 60]
    }
    frozen = {
        "design_sha256": hashlib.sha256(DESIGN_PATH.read_bytes()).hexdigest(),
        "source_sha256": source_hashes(),
        "test_data_sha256": hashlib.sha256(
            (ROOT / "test.pkl").read_bytes()
        ).hexdigest(),
        "model_sha256": hashlib.sha256(
            (ROOT / "frozen_model.joblib").read_bytes()
        ).hexdigest(),
        "training_rows": len(training),
        "training_end": training.date.max(),
        "training_stocks": sorted(training.symbol.unique()),
        "feature_names": names,
        "majority_mappings": mapping,
        "chosen": chosen,
        "candidate_count": len(candidates()),
        "threshold_search_count": len(choices),
        "primary_test_excludes": ["TCS"],
        "cold_stocks": sorted(COLD_STOCKS),
    }
    (ROOT / "frozen.json").write_text(json.dumps(frozen, indent=2))
    print("Model/threshold frozen; final-test data has not been loaded", flush=True)


def evaluate():
    frozen = json.loads((ROOT / "frozen.json").read_text())
    if hashlib.sha256(DESIGN_PATH.read_bytes()).hexdigest() != frozen["design_sha256"]:
        raise RuntimeError("Design changed after freezing")
    if (
        hashlib.sha256((ROOT / "frozen_model.joblib").read_bytes()).hexdigest()
        != frozen["model_sha256"]
    ):
        raise RuntimeError("Frozen model changed")
    if source_hashes() != frozen["source_sha256"]:
        raise RuntimeError("Research source changed after freezing")
    if (
        hashlib.sha256((ROOT / "test.pkl").read_bytes()).hexdigest()
        != frozen["test_data_sha256"]
    ):
        raise RuntimeError("Test data changed after freezing")
    model = joblib.load(ROOT / "frozen_model.joblib")
    test_all = pd.read_pickle(ROOT / "test.pkl")
    chosen = frozen["chosen"]
    config, threshold = chosen["config"], chosen["threshold"]
    results = []
    primary_metrics = None
    cold_metrics = None
    prediction_files = []
    for horizon in [30, 15, 60]:
        test = with_majority(
            test_all[test_all.horizon_minutes == horizon].reset_index(drop=True),
            frozen["majority_mappings"][str(horizon)],
        )
        raw = predict(model, config, test, frozen["feature_names"])
        signs = action(raw, config, threshold)
        predictions = test[
            [
                "symbol",
                "sector",
                "date",
                "decision_time",
                "position",
                "return_bp",
                "majority_direction",
                "rrs_direction",
                "momentum_direction",
                "ema_direction",
            ]
        ].copy()
        predictions["prediction"] = signs
        predictions["horizon_minutes"] = horizon
        prediction_files.append(predictions)
        groups = {
            "primary_unseen_outcomes_19_stocks": test.symbol != "TCS",
            "cold_stocks_never_trained": test.symbol.isin(COLD_STOCKS),
            "familiar_stocks_excluding_TCS": ~test.symbol.isin(COLD_STOCKS | {"TCS"}),
            "TCS_previously_inspected_secondary": test.symbol == "TCS",
        }
        for group, mask in groups.items():
            frame = test.loc[mask].reset_index(drop=True)
            for rule, prediction in [
                ("tuned_candidate", signs[mask]),
                ("current_rrs", frame.rrs_direction.to_numpy()),
                ("15min_momentum", frame.momentum_direction.to_numpy()),
                ("ema8_21", frame.ema_direction.to_numpy()),
                ("training_majority", frame.majority_direction.to_numpy()),
            ]:
                metrics = score(frame, prediction, horizon // 5, intervals=True)
                results.append(
                    {
                        "group": group,
                        "horizon_minutes": horizon,
                        "rule": rule,
                        **metrics,
                    }
                )
                if (
                    group == "primary_unseen_outcomes_19_stocks"
                    and horizon == 30
                    and rule == "tuned_candidate"
                ):
                    primary_metrics = metrics
                if (
                    group == "cold_stocks_never_trained"
                    and horizon == 30
                    and rule == "tuned_candidate"
                ):
                    cold_metrics = metrics
    pd.concat(prediction_files, ignore_index=True).to_csv(
        ROOT / "test_predictions.csv", index=False
    )
    gates = DESIGN["deployment_gates"]
    net_ci = primary_metrics.get("net_bp_day_bootstrap_95_ci")
    excess_ci = primary_metrics.get("accuracy_excess_vs_majority_day_bootstrap_95_ci")
    net_block_ci = primary_metrics.get("net_bp_5day_block_bootstrap_95_ci")
    excess_block_ci = primary_metrics.get(
        "accuracy_excess_vs_majority_5day_block_bootstrap_95_ci"
    )
    checks = {
        "selection_passed_before_test": chosen["selection_passed"],
        "enough_predictions": primary_metrics["predictions"]
        >= gates["test_min_predictions"],
        "enough_bullish_predictions": primary_metrics.get("bullish_predictions", 0)
        >= gates["test_min_bullish_predictions"],
        "enough_bearish_predictions": primary_metrics.get("bearish_predictions", 0)
        >= gates["test_min_bearish_predictions"],
        "coverage": primary_metrics["actionable_bar_coverage"]
        >= gates["test_min_coverage"],
        "sector_diversity": primary_metrics["sectors"] >= gates["test_min_sectors"],
        "positive_net_return_lower_bound": bool(net_ci and net_ci[0] > 0),
        "beats_majority_lower_bound": bool(excess_ci and excess_ci[0] > 0),
        "positive_net_return_5day_block_lower_bound": bool(
            net_block_ci and net_block_ci[0] > 0
        ),
        "beats_majority_5day_block_lower_bound": bool(
            excess_block_ci and excess_block_ci[0] > 0
        ),
        "positive_cold_stock_net_return": cold_metrics.get("mean_net_bp", -np.inf) > 0,
    }
    report = {
        "frozen": frozen,
        "design": DESIGN,
        "results": results,
        "deployment_checks": checks,
        "deployment_suitable": bool(all(checks.values())),
        "limitations": [
            "Fixed current liquid-stock universe has survivorship bias; it is not the entire market.",
            "Historical candles may have later revisions; no point-in-time live publication archive exists.",
            "Costs are illustrative, fills assume next-open execution without delay.",
            "Overlapping raw bars are not independent; scoring thins within stocks and bootstraps whole market dates.",
            "No live-feed/trading APIs were called, and no production signals were changed.",
            "30 minutes is the trained target; 15/60 minutes are secondary outcome checks of the same frozen rule.",
        ],
    }
    (ROOT / "final_test.json").write_text(json.dumps(report, indent=2))
    print("FINAL 30-MINUTE PRIMARY RESULT", json.dumps(primary_metrics), flush=True)
    print("COLD STOCK RESULT", json.dumps(cold_metrics), flush=True)
    print("DEPLOYMENT GATES", json.dumps(checks), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["tune", "evaluate"])
    phase = parser.parse_args().phase
    tune() if phase == "tune" else evaluate()
