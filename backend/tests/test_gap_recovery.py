from datetime import datetime
from pathlib import Path
import numpy as np, pandas as pd
from app.contracts import Instrument
from app.provider import GrowwProvider
from app.indicators import COLS, TZ, parse_candles
from app.sessions import continuous_grid
import pytest

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


def test_all_quarantined_prices_are_recoverable(tmp_path, monkeypatch):
    monkeypatch.setattr("app.provider.time.sleep", lambda _: None)
    rows = complete_rows()
    invalid = [[r[0], 0, 0, 0, 0, r[5]] for r in rows]
    provider = GrowwProvider(tmp_path)
    provider.api = API(invalid, rows)
    data = provider.fetch(INSTRUMENT, START, END)
    assert data.close.notna().all() and len(data) == 72
    assert data.attrs["parser_diagnostics"]["quarantined_price_rows"] == 72
    assert data.attrs["gap_recovery"]["recovered_price_bars"] == 72


def test_empty_response_retains_cache_for_peer_recovery(tmp_path, monkeypatch):
    monkeypatch.setattr("app.provider.time.sleep", lambda _: None)
    rows = complete_rows()
    provider = GrowwProvider(tmp_path)
    provider.api = API([], rows)
    empty = provider.fetch(INSTRUMENT, START, END)
    assert empty.empty and empty.attrs["_cache_chunks"]
    recovered = provider.repair_gaps(
        INSTRUMENT, empty, START, END, session_dates=[START.normalize()]
    )
    assert recovered.close.notna().all() and len(recovered) == 72
    calls = len(provider.api.calls)
    again = provider.fetch(INSTRUMENT, START, END)
    assert again.close.notna().all() and len(provider.api.calls) == calls


def test_auction_only_response_waits_for_peer_observed_session(tmp_path, monkeypatch):
    monkeypatch.setattr("app.provider.time.sleep", lambda _: None)
    auction = [[END.isoformat(), 100, 101, 99, 100, 1000]]
    provider = GrowwProvider(tmp_path)
    provider.api = API(auction, complete_rows())
    empty = provider.fetch(INSTRUMENT, START, END + pd.Timedelta(minutes=5))
    assert empty.empty and len(provider.api.calls) == 1
    assert empty.attrs["parser_diagnostics"]["excluded_noncontinuous_rows"] == 1
    recovered = provider.repair_gaps(
        INSTRUMENT, empty, START, END, session_dates=[START.normalize()]
    )
    assert len(recovered) == 72 and recovered.close.notna().all()


def test_allow_unusable_does_not_accept_conflicting_duplicates(tmp_path, monkeypatch):
    import pytest
    from app.provider import ProviderError

    monkeypatch.setattr("app.provider.time.sleep", lambda _: None)
    rows = complete_rows()
    duplicate = rows[0].copy()
    duplicate[4] += 0.5
    provider = GrowwProvider(tmp_path)
    provider.api = API([*rows, duplicate], rows)
    with pytest.raises(ProviderError) as error:
        provider.fetch(INSTRUMENT, START, END)
    assert error.value.code == "history_invalid" and len(provider.api.calls) == 1


@pytest.mark.parametrize("initial_kind", ["empty", "invalid", "auction"])
def test_peer_recovered_benchmark_scan_exports_and_cache(
    tmp_path, monkeypatch, initial_kind
):
    import csv, io, json, zipfile
    from app.contracts import ScanRequest
    from app.service import Workspace

    monkeypatch.setattr("app.provider.time.sleep", lambda _: None)
    rows = complete_rows()
    initial = {
        "empty": [],
        "invalid": [[r[0], 0, 0, 0, 0, r[5]] for r in rows],
        "auction": [[END.isoformat(), 100, 101, 99, 100, 1000]],
    }[initial_kind]
    catalog = [
        INSTRUMENT,
        INSTRUMENT.model_copy(update={"symbol": "NIFTY 50", "kind": "index"}),
        INSTRUMENT.model_copy(update={"symbol": "NIFTYBEES", "kind": "etf"}),
    ]
    # Distinct broker identities must have distinct cache keys.
    catalog = [
        item.model_copy(update={"groww_symbol": item.symbol}) for item in catalog
    ]
    (tmp_path / "instruments.json").write_text(
        json.dumps([item.model_dump() for item in catalog])
    )
    workspace = Workspace(tmp_path, tmp_path / "cache")
    workspace.provider.api = API(initial, rows)
    request = ScanRequest(start=START.to_pydatetime(), end=END.to_pydatetime())
    snapshot = workspace.scan(request)
    chart = workspace.charts["TCS"]
    assert chart.quality == snapshot.rows[0]
    assert chart.points[-1].close == snapshot.rows[0].close
    assert chart.points[-1].features["rrs"] == snapshot.rows[0].rrs
    assert workspace.export_run.inputs["NIFTY 50"].close.notna().all()
    exported = list(
        csv.DictReader(io.StringIO(workspace.export_run.csv("TCS").decode("utf-8-sig")))
    )
    assert (
        len(exported) == 72 and float(exported[-1]["close"]) == chart.points[-1].close
    )
    with zipfile.ZipFile(io.BytesIO(workspace.export_run.bundle())) as bundle:
        assert bundle.read("results/TCS.csv") == workspace.export_run.csv("TCS")
        assert json.loads(bundle.read("manifest.json"))["request"]["live"] is False
    calls = len(workspace.provider.api.calls)
    workspace.scan(request)
    assert len(workspace.provider.api.calls) == calls
