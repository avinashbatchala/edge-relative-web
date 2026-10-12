import pandas as pd
import numpy as np
from app.contracts import Instrument
from app.sessions import continuous_grid, expected_slot
from app.indicators import parse_candles, aligned_grid, oscillators, PARAMS, COLS, TZ


def test_cas_date_boundary_and_other_market_profiles():
    cas = Instrument(symbol="TCS", kind="stock", session_profile="nse_cas")
    cash = Instrument(symbol="NIFTYBEES", kind="etf")
    before = continuous_grid([pd.Timestamp("2026-07-31", tz=TZ)], cas)
    after = continuous_grid([pd.Timestamp("2026-08-03", tz=TZ)], cas)
    assert len(before) == 75 and before[-1].strftime("%H:%M") == "15:25"
    assert len(after) == 72 and after[-1].strftime("%H:%M") == "15:10"
    assert len(continuous_grid([pd.Timestamp("2026-08-03", tz=TZ)], cash)) == 75


def test_only_completed_requested_slots_and_no_weekend():
    cash = Instrument(symbol="TCS", kind="stock", session_profile="nse_cas")
    grid = continuous_grid(
        [pd.Timestamp("2026-10-12", tz=TZ), pd.Timestamp("2026-10-11", tz=TZ)],
        cash,
        start=pd.Timestamp("2026-10-12 09:20", tz=TZ),
        asof=pd.Timestamp("2026-10-12 09:31", tz=TZ),
    )
    assert grid.strftime("%H:%M").tolist() == ["09:20", "09:25"]
    assert (
        expected_slot(pd.Timestamp("2026-10-12 16:00", tz=TZ), cash, 20).strftime(
            "%H:%M"
        )
        == "15:10"
    )
    assert expected_slot(pd.Timestamp("2026-10-12 09:20:10", tz=TZ), cash, 20) is None


def test_parser_separates_auction_rows_before_price_validation():
    rows = [
        ["2026-10-12T15:10:00", 100, 101, 99, 100, 10],
        ["2026-10-12T15:20:00", 0, 0, 0, 0, -1],
        ["2026-10-12T15:25:00", 105, 105, 105, 105, 20],
    ]
    data = parse_candles(
        {"candles": rows},
        now=pd.Timestamp("2026-10-12 16:00", tz=TZ),
        session_profile="nse_cas",
    )
    assert len(data) == 1 and data.close.iloc[0] == 100
    report = data.attrs["parser_diagnostics"]
    assert report["excluded_noncontinuous_rows"] == 2
    assert report["quarantined_price_rows"] == 0


def test_cas_grid_does_not_reinsert_auction_gap_or_reset_next_morning():
    days = pd.date_range("2026-10-08", "2026-10-09", tz=TZ)
    instrument = Instrument(symbol="TCS", kind="stock", session_profile="nse_cas")
    index = continuous_grid(days, instrument)
    close = 100 + np.arange(len(index)) * 0.1
    frame = pd.DataFrame(
        {
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 100 + np.arange(len(index)) ** 2,
        },
        index=index,
    )
    aligned, _ = aligned_grid(
        {"stock": frame, "benchmark": frame},
        asof=pd.Timestamp("2026-10-09 16:00", tz=TZ),
        session_profile="nse_cas",
    )
    assert len(aligned["stock"]) == 144
    result = oscillators(aligned["stock"], aligned["benchmark"], aligned["stock"])
    assert result.rrs.loc["2026-10-09 09:15":"2026-10-09 10:10"].notna().all()
