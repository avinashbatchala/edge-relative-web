import json
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from app.contracts import ScanRequest
from app.service import Workspace
from app.indicators import COLS, TZ


class FixtureProvider:
    def connect(self):
        return self

    def configured(self):
        return True

    def fetch(self, item, start, end, interval=5, refresh=False):
        if interval == 1440:
            index = pd.bdate_range("2026-01-01", periods=130, tz=TZ)
        else:
            days = pd.bdate_range("2026-08-03", "2026-08-06", tz=TZ)
            index = pd.DatetimeIndex(
                [
                    t
                    for d in days
                    for t in pd.date_range(
                        d + pd.Timedelta(hours=9, minutes=15), periods=75, freq="5min"
                    )
                ]
            )
        offset = {"TCS": 100, "NIFTY 50": 200, "NIFTYBEES": 50, "NIFTY IT": 150}[
            item.symbol
        ]
        close = (
            offset + np.arange(len(index)) * 0.05 + np.sin(np.arange(len(index)) * 0.4)
        )
        return pd.DataFrame(
            {
                "open": close - 0.1,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "volume": 1000 + np.arange(len(index)) ** 2,
            },
            index=index,
        )


def workspace(tmp_path):
    data = [
        {
            "symbol": name,
            "kind": kind,
            "groww_symbol": name,
            "exchange_token": name,
            **({"sector": "NIFTY IT"} if name == "TCS" else {}),
        }
        for name, kind in [
            ("TCS", "stock"),
            ("NIFTY 50", "index"),
            ("NIFTYBEES", "etf"),
            ("NIFTY IT", "index"),
        ]
    ]
    (tmp_path / "instruments.json").write_text(json.dumps(data))
    w = Workspace(tmp_path, tmp_path / "cache")
    w.provider = FixtureProvider()
    return w


def test_chart_and_scanner_share_exact_completed_values(tmp_path):
    w = workspace(tmp_path)
    result = w.scan(
        ScanRequest(start="2026-08-03T03:45:00Z", end="2026-08-06T10:00:00Z")
    )
    row = result.rows[0]
    point = w.charts["TCS"].points[-1]
    assert (
        row.rrs == point.features["rrs"]
        and row.close == point.close
        and row.candle_time == point.time
    )
    assert row.quality == "historical"
    assert w.charts["TCS"].sector_benchmark == "NIFTY IT"
    assert "NaN" not in result.model_dump_json()


def test_status_reports_whether_a_confirmed_snapshot_exists(tmp_path):
    w = workspace(tmp_path)
    assert w.status().snapshot_available is False
    w.scan(ScanRequest(start="2026-08-03T03:45:00Z", end="2026-08-06T10:00:00Z"))
    assert w.status().snapshot_available is True


def test_missing_sector_filter_fails_closed(tmp_path):
    w = workspace(tmp_path)
    w.instruments[0] = w.instruments[0].model_copy(update={"sector": "UNKNOWN"})
    result = w.scan(
        ScanRequest(
            start="2026-08-03T03:45:00Z", end="2026-08-06T10:00:00Z", sector_filter=True
        )
    )
    assert result.rows[0].direction == "unavailable"
    assert any("Sector filter unavailable" in x for x in result.rows[0].reasons)


def test_volume_proxy_failure_preserves_price_studies(tmp_path):
    from app.provider import ProviderError

    w = workspace(tmp_path)
    original = w.provider.fetch

    def fetch(item, *args, **kwargs):
        if item.symbol == "NIFTYBEES":
            raise ProviderError("history_fetch_failed", "Volume proxy absent")
        return original(item, *args, **kwargs)

    w.provider.fetch = fetch
    result = w.scan(
        ScanRequest(start="2026-08-03T03:45:00Z", end="2026-08-06T10:00:00Z")
    )
    assert result.rows[0].rrs is not None and result.rows[0].rrv is None
    assert "NIFTYBEES" in result.diagnostics["fetch_failures"]


def test_failed_reconciliation_revokes_scan_direction(tmp_path):
    import asyncio

    w = workspace(tmp_path)
    w.scan(ScanRequest(start="2026-08-03T03:45:00Z", end="2026-08-06T10:00:00Z"))
    asyncio.run(w.mark_stale())
    assert (
        w.snapshot.rows[0].direction == "unavailable"
        and w.snapshot.rows[0].quality == "stale"
    )
    assert w.charts["TCS"].quality.quality == "stale"


def test_cas_comparison_and_exports_share_session_policy(tmp_path):
    import io, csv, zipfile

    w = workspace(tmp_path)
    w.instruments[0] = w.instruments[0].model_copy(
        update={"session_profile": "nse_cas"}
    )
    result = w.scan(
        ScanRequest(start="2026-08-03T03:45:00Z", end="2026-08-06T10:00:00Z")
    )
    chart = w.charts["TCS"]
    assert chart.session_profile == "nse_cas" and len(chart.points) == 4 * 72
    assert (
        pd.Timestamp(chart.points[-1].time, unit="s", tz="UTC")
        .tz_convert(TZ)
        .strftime("%H:%M")
        == "15:10"
    )
    assert result.rows[0].rrs == chart.points[-1].features["rrs"]
    assert (
        w.expected_slot(pd.Timestamp("2026-08-06 16:00", tz=TZ), "nse_cas").strftime(
            "%H:%M"
        )
        == "15:10"
    )
    exported = list(
        csv.DictReader(io.StringIO(w.export_run.csv("TCS").decode("utf-8-sig")))
    )
    assert len(exported) == 288 and exported[-1]["session_profile"] == "nse_cas"
    with zipfile.ZipFile(io.BytesIO(w.export_run.bundle())) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        assert manifest["session_profiles_by_symbol"]["TCS"] == "nse_cas"
        assert "engine/sessions.py" in bundle.namelist()
        assert "engine/provider.py" in bundle.namelist()
        proxy = list(
            csv.DictReader(
                io.StringIO(bundle.read("inputs/NIFTYBEES_5m.csv").decode("utf-8-sig"))
            )
        )
        assert (
            len(proxy) == 300
        )  # Broker source retains the ETF's later trading window.


def test_empty_benchmark_can_be_recovered_from_peer_observed_dates(tmp_path):
    from app.provider import ProviderError

    w = workspace(tmp_path)
    original = w.provider.fetch
    calls = []

    def fetch(item, *args, **kwargs):
        if item.symbol == "NIFTY 50" and kwargs.get("interval", 5) == 5:
            raise ProviderError("history_empty", "No benchmark candles")
        return original(item, *args, **kwargs)

    def repair(item, data, start, end, session_dates=None):
        calls.append((item.symbol, session_dates))
        result = original(item, start, end)
        result.attrs["gap_recovery"] = {"requests": 1, "remaining_price_gaps": 0}
        return result

    w.provider.fetch = fetch
    w.provider.repair_gaps = repair
    result = w.scan(
        ScanRequest(start="2026-08-03T03:45:00Z", end="2026-08-06T10:00:00Z")
    )
    assert calls[0][0] == "NIFTY 50" and len(calls[0][1]) == 4
    assert "NIFTY 50" not in result.diagnostics["fetch_failures"]
    assert result.rows[0].rrs is not None
    assert result.diagnostics["NIFTY 50"]["gap_recovery"]["requests"] == 1
