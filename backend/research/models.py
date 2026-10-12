"""Fixed research candidates and transparent abstention thresholds."""

import numpy as np
from itertools import product
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
)
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


def candidates():
    return (
        [
            {
                "family": "rule",
                "length": length,
                "confirmation": confirmation,
                "ema_agreement": ema,
                "strength": strength,
            }
            for length, confirmation, ema, strength in product(
                [8, 12, 20], [1, 2, 3], [False, True], [0, 0.5]
            )
        ]
        + [{"family": "logistic", "C": value} for value in [0.01, 0.1, 1.0]]
        + [
            {"family": family, "leaves": value}
            for family in ["boosted_classifier", "boosted_regressor"]
            for value in [7, 15, 31]
        ]
    )


def make_model(config):
    if config["family"] == "rule":
        return config
    if config["family"] == "logistic":
        return make_pipeline(
            SimpleImputer(strategy="median", add_indicator=True),
            StandardScaler(),
            LogisticRegression(C=config["C"], max_iter=1000, random_state=20261012),
        )
    args = dict(
        max_leaf_nodes=config["leaves"],
        learning_rate=0.05,
        max_iter=150,
        min_samples_leaf=100,
        l2_regularization=10,
        early_stopping=False,
        random_state=20261012,
    )
    if config["family"] == "boosted_classifier":
        return HistGradientBoostingClassifier(**args)
    return HistGradientBoostingRegressor(**args)


def raw_prediction(model, config, features):
    if config["family"] == "rule":
        length = config["length"]
        sign = features[f"rrs{length}_direction"].to_numpy()
        valid = (features[f"rrs{length}_value"].abs() >= config["strength"]) & (
            features[f"rrs{length}_run"] >= config["confirmation"]
        )
        if config["ema_agreement"]:
            valid &= sign == np.sign(features.ema8_21_gap_bp)
        return np.where(valid, sign, 0)
    if config["family"] == "boosted_regressor":
        return model.predict(features)
    probabilities = model.predict_proba(features)
    # Training must include down, flat and up; do not assume missing class columns.
    if list(model.classes_) != [0, 1, 2]:
        raise ValueError("Training did not contain every direction/noise class")
    return probabilities


def action(raw, config, threshold):
    if config["family"] == "rule":
        return np.asarray(raw, dtype=int)
    if config["family"] == "boosted_regressor":
        return np.where(np.abs(raw) >= threshold, np.sign(raw), 0).astype(int)
    down, flat, up = raw[:, 0], raw[:, 1], raw[:, 2]
    return np.select(
        [
            (up > down) & (up > flat) & (up >= threshold),
            (down > up) & (down > flat) & (down >= threshold),
        ],
        [1, -1],
        default=0,
    )


def thresholds(config):
    if config["family"] == "rule":
        return [0]
    return (
        [5, 10, 15, 20]
        if config["family"] == "boosted_regressor"
        else [0.4, 0.45, 0.5, 0.55, 0.6]
    )


def majority_maps(data):
    direction = lambda returns: 1 if (returns > 0).sum() >= (returns < 0).sum() else -1
    return {
        "stock": {
            name: direction(group.return_bp) for name, group in data.groupby("symbol")
        },
        "sector": {
            name: direction(group.return_bp) for name, group in data.groupby("sector")
        },
        "global": direction(data.return_bp),
    }


def with_majority(data, mapping):
    result = data.copy()
    result["majority_direction"] = [
        mapping["stock"].get(
            row.symbol, mapping["sector"].get(row.sector, mapping["global"])
        )
        for row in result.itertuples()
    ]
    return result


def fixed_clock_sample(data, horizon=30):
    decision = data.decision_time.dt.hour * 60 + data.decision_time.dt.minute
    return data[(decision - 585) % horizon == 0].reset_index(drop=True)
