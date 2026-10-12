import numpy as np
import pandas as pd
import pytest
from research.dataset import forward_labels
from research.metrics import nonoverlap
from research.models import action, majority_maps, with_majority


def candles(index):
    prices = np.arange(len(index), dtype=float) + 100
    return pd.DataFrame(
        {
            "open": prices,
            "high": prices + 1,
            "low": prices - 1,
            "close": prices + 0.5,
            "volume": 1000,
        },
        index=index,
    )


def test_entry_is_next_open_not_signal_close():
    stock = candles(
        pd.date_range("2026-09-22 09:15", periods=8, freq="5min", tz="Asia/Kolkata")
    )
    result = forward_labels(stock, 3)
    assert result.iloc[0] == pytest.approx((103.5 / 101 - 1) * 10000)
    assert result.iloc[-3:].isna().all()


def test_gap_invalidates_the_entire_forward_path():
    stock = candles(
        pd.date_range("2026-09-22 09:15", periods=10, freq="5min", tz="Asia/Kolkata")
    )
    stock.iloc[2] = np.nan
    result = forward_labels(stock, 3)
    assert result.iloc[:3].isna().all()
    assert pd.notna(result.iloc[3])


def test_horizon_never_crosses_session_or_time_hole():
    first = pd.date_range("2026-09-22 14:55", periods=4, freq="5min", tz="Asia/Kolkata")
    second = pd.date_range(
        "2026-09-23 09:15", periods=4, freq="5min", tz="Asia/Kolkata"
    )
    result = forward_labels(candles(first.append(second)), 3)
    assert pd.notna(result.iloc[0]) and result.iloc[1:4].isna().all()
    sparse = candles(
        pd.date_range(
            "2026-09-22 09:15", periods=8, freq="5min", tz="Asia/Kolkata"
        ).delete(2)
    )
    assert pd.isna(forward_labels(sparse, 3).iloc[0])


def test_overlapping_calls_are_thinned_per_stock_not_globally():
    rows = [
        {
            "symbol": symbol,
            "date": "2026-09-22",
            "position": i,
            "decision_time": pd.Timestamp("2026-09-22 09:45")
            + pd.Timedelta(minutes=5 * i),
        }
        for symbol in ["TCS", "INFY"]
        for i in range(7)
    ]
    selected = nonoverlap(pd.DataFrame(rows), np.ones(14), 3)
    assert selected.groupby("symbol").position.apply(list).to_dict() == {
        "INFY": [0, 3, 6],
        "TCS": [0, 3, 6],
    }


def test_flat_or_uncertain_classifier_predictions_abstain():
    probabilities = np.array(
        [[0.2, 0.6, 0.2], [0.25, 0.26, 0.49], [0.1, 0.2, 0.7], [0.7, 0.2, 0.1]]
    )
    assert action(probabilities, {"family": "logistic"}, 0.55).tolist() == [0, 0, 1, -1]


def test_untrained_stock_baseline_uses_training_sector_not_test_returns():
    training = pd.DataFrame(
        {"symbol": ["TCS"] * 3, "sector": ["IT"] * 3, "return_bp": [-20, -10, 5]}
    )
    test = pd.DataFrame({"symbol": ["INFY"], "sector": ["IT"], "return_bp": [999]})
    assert with_majority(test, majority_maps(training)).majority_direction.iloc[0] == -1


def test_final_test_cannot_be_reused_to_retune(tmp_path, monkeypatch):
    import research.tune as runner

    monkeypatch.setattr(runner, "ROOT", tmp_path)
    (tmp_path / "final_test.json").write_text("{}")
    with pytest.raises(RuntimeError, match="already inspected"):
        runner.tune()
