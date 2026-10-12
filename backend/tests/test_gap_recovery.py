from datetime import datetime
from pathlib import Path
import numpy as np, pandas as pd
from app.contracts import Instrument
from app.provider import GrowwProvider
from app.indicators import COLS, TZ, parse_candles
from app.sessions import continuous_grid

INSTRUMENT = Instrument(
    symbol="TCS",
    kind="stock",
    groww_symbol="NSE-TCS",
    exchange_token="11536",
    session_profile="nse_cas",
)
START = pd.Timestamp("2026-09-29 09:15", tz=TZ)
END = pd.Timestamp("2026-09-29 15:15", tz=TZ)


def complete_rows():
    return [
        [t.isoformat(), 100 + i, 101 + i, 99 + i, 100 + i, 1000 + i]
        for i, t in enumerate(continuous_grid([START.normalize()], INSTRUMENT))
    ]


class API:
    CANDLE_INTERVAL_MIN_5 = "5minute"
    CANDLE_INTERVAL_DAY = "1day"

    def __init__(self, first, recovery):
        self.first = first
        self.recovery = recovery
        self.calls = []

    def get_historical_candles(self, **kwargs):
        self.calls.append(kwargs)
        return {"candles": self.first if len(self.calls) == 1 else self.recovery}


def test_recovers_tail_gap_without_fabrication(tmp_path, monkeypatch):
    monkeypatch.setattr("app.provider.time.sleep", lambda _: None)
    rows = complete_rows()
    api = API(rows[:57], rows[57:])
    provider = GrowwProvider(tmp_path)
    provider.api = api
    data = provider.fetch(INSTRUMENT, START, END)
    assert len(data) == 72 and data.close.iloc[-1] == 171
    diagnostics = data.attrs["gap_recovery"]
    assert (
        diagnostics["recovered_price_bars"] == 15
        and diagnostics["remaining_price_gaps"] == 0
    )
    assert api.calls[1]["start_time"] == "2026-09-29 14:00:00"
    assert len(api.calls) == 2


def test_unrecoverable_gap_remains_missing_and_retry_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr("app.provider.time.sleep", lambda _: None)
    rows = complete_rows()
    api = API(rows[:57], [])
    provider = GrowwProvider(tmp_path)
    provider.api = api
    data = provider.fetch(INSTRUMENT, START, END)
    assert len(data) == 72 and data.iloc[57:].isna().all().all()
    report = data.attrs["gap_recovery"]
    assert report["remaining_price_gaps"] == 15 and report["requests"] == 2
    assert report["recovered_price_bars"] == 0 and len(api.calls) == 3


def test_invalid_recovery_and_conflicting_overlap_do_not_replace_valid_prices(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("app.provider.time.sleep", lambda _: None)
    rows = complete_rows()
    recovery = [r.copy() for r in rows[55:]]
    recovery[0][4] = 9999
    recovery[2][2] = 0
    provider = GrowwProvider(tmp_path)
    provider.api = API(rows[:57], recovery)
    data = provider.fetch(INSTRUMENT, START, END)
    assert data.close.iloc[55] == 155 and pd.isna(data.close.iloc[57])
    assert data.close.iloc[58] == 158


def test_cached_holes_are_repaired_and_complete_cache_is_reused(tmp_path, monkeypatch):
    import json, hashlib

    monkeypatch.setattr("app.provider.time.sleep", lambda _: None)
    rows = complete_rows()
    provider = GrowwProvider(tmp_path)
    api = API(rows, rows)
    provider.api = api
    # Warm complete cache, replace the broker response with an incomplete historical response.
    provider.fetch(INSTRUMENT, START, END)
    cache = next(tmp_path.glob("*.json"))
    cache.write_text(json.dumps({"candles": rows[:57]}))
    data = provider.fetch(INSTRUMENT, START, END)
    assert len(data) == 72 and data.close.notna().all()
    calls = len(api.calls)
    again = provider.fetch(INSTRUMENT, START, END)
    assert len(api.calls) == calls and again.close.notna().all()


def test_does_not_retry_missing_index_volume_or_cas_slots(tmp_path, monkeypatch):
    monkeypatch.setattr("app.provider.time.sleep", lambda _: None)
    rows = complete_rows()
    for row in rows:
        row[5] = None
    provider = GrowwProvider(tmp_path)
    provider.api = API(rows, [])
    index = INSTRUMENT.model_copy(update={"kind": "index"})
    data = provider.fetch(index, START, END)
    assert len(provider.api.calls) == 1 and data.volume.isna().all()


def test_peer_trading_dates_recover_a_fully_missing_session(tmp_path, monkeypatch):
    monkeypatch.setattr("app.provider.time.sleep", lambda _: None)
    rows = complete_rows()
    provider = GrowwProvider(tmp_path)
    provider.api = API(rows, rows)
    empty = pd.DataFrame(columns=COLS, index=pd.DatetimeIndex([], tz=TZ), dtype=float)
    data = provider.repair_gaps(
        INSTRUMENT, empty, START, END, session_dates=[START.normalize()]
    )
    assert len(data) == 72 and data.close.notna().all()


def test_many_disjoint_gaps_share_one_request_budget(tmp_path, monkeypatch):
    monkeypatch.setattr("app.provider.time.sleep", lambda _: None)
    rows = complete_rows()
    provider = GrowwProvider(tmp_path)
    provider.api = API([r for i, r in enumerate(rows) if i % 4 != 0], [])
    data = provider.fetch(INSTRUMENT, START, END)
    assert len(provider.api.calls) == 9  # One initial fetch, at most eight repairs.
    assert data.attrs["gap_recovery"]["requests"] == 8
    assert data.attrs["gap_recovery"]["remaining_price_gaps"] == 18


def test_volume_repair_requires_matching_ohlc(tmp_path, monkeypatch):
    monkeypatch.setattr("app.provider.time.sleep", lambda _: None)
    rows = complete_rows()
    initial = [r.copy() for r in rows]
    initial[20][5] = None
    changed = [r.copy() for r in rows]
    changed[20][1:5] = [120.5, 121.5, 119.5, 120.5]
    provider = GrowwProvider(tmp_path)
    provider.api = API(initial, changed)
    data = provider.fetch(INSTRUMENT, START, END)
    assert data.close.iloc[20] == 120 and pd.isna(data.volume.iloc[20])
    assert data.attrs["gap_recovery"]["remaining_volume_gaps"] == 1


def test_unobserved_weekday_is_not_a_holiday_gap(tmp_path, monkeypatch):
    monkeypatch.setattr("app.provider.time.sleep", lambda _: None)
    rows = complete_rows()
    provider = GrowwProvider(tmp_path)
    provider.api = API(rows, [])
    data = provider.fetch(INSTRUMENT, START - pd.Timedelta(days=1), END)
    assert len(data) == 72 and len(provider.api.calls) == 1
    assert set(data.index.date) == {START.date()}


def test_matching_volume_repair_is_persisted(tmp_path, monkeypatch):
    monkeypatch.setattr("app.provider.time.sleep", lambda _: None)
    rows = complete_rows()
    initial = [r.copy() for r in rows]
    initial[20][5] = None
    provider = GrowwProvider(tmp_path)
    provider.api = API(initial, rows)
    data = provider.fetch(INSTRUMENT, START, END)
    assert data.volume.iloc[20] == 1020
    assert data.attrs["gap_recovery"]["recovered_volume_bars"] == 1
    calls = len(provider.api.calls)
    again = provider.fetch(INSTRUMENT, START, END)
    assert again.volume.iloc[20] == 1020 and len(provider.api.calls) == calls


def test_peer_session_repair_updates_historical_cache(tmp_path, monkeypatch):
    monkeypatch.setattr("app.provider.time.sleep", lambda _: None)
    rows = complete_rows()
    following = [
        [(pd.Timestamp(r[0]) + pd.Timedelta(days=1)).isoformat(), *r[1:]] for r in rows
    ]
    provider = GrowwProvider(tmp_path)
    provider.api = API(rows, following)
    end = END + pd.Timedelta(days=1)
    data = provider.fetch(INSTRUMENT, START, end)
    assert len(data) == 72
    repaired = provider.repair_gaps(
        INSTRUMENT,
        data,
        START,
        end,
        session_dates=[START.normalize(), START.normalize() + pd.Timedelta(days=1)],
    )
    assert len(repaired) == 144 and repaired.close.notna().all()
    calls = len(provider.api.calls)
    again = provider.fetch(INSTRUMENT, START, end)
    assert len(again) == 144 and len(provider.api.calls) == calls
