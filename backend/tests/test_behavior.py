from datetime import datetime, timezone
import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from app.indicators import wa, oscillators, parse_candles, TZ
from app.scanner import classify
from app.main import create_app
from app.contracts import ScanRequest


def test_wilder_seed_and_gap_reset():
    got = wa(pd.Series([1.0, 2.0, 3.0, np.nan, 4.0, 5.0, 6.0]), 2)
    assert np.allclose(got.iloc[[1, 2, 5, 6]], [1.5, 2.25, 4.5, 5.25])
    assert got.iloc[[0, 3, 4]].isna().all()


def test_no_forming_bar_or_invalid_price_enters_features():
    now = pd.Timestamp("2026-10-12 09:42", tz=TZ)
    rows = [
        ["2026-10-12T09:30:00", 10, 11, 9, 10, 100],
        ["2026-10-12T09:35:00", 10, 0, 9, 10, 100],
        ["2026-10-12T09:40:00", 10, 11, 9, 10, 100],
    ]
    data = parse_candles({"candles": rows}, now=now)
    assert len(data) == 2 and data.iloc[1].isna().all()
    assert data.attrs["parser_diagnostics"]["quarantined_price_rows"] == 1


def test_index_volume_missing_keeps_price():
    data = parse_candles(
        {"candles": [["2026-10-12T09:30:00", 10, 11, 9, 10, -1]]},
        now=pd.Timestamp("2026-10-12 10:00", tz=TZ),
    )
    assert data.close.iloc[0] == 10 and pd.isna(data.volume.iloc[0])


def test_direction_and_missing_values():
    assert classify(2.0, 1.0)[0] == "bullish"
    assert classify(-2.0, -1.0)[0] == "bearish"
    assert classify(1.0, 2.0)[0] == "mixed"
    assert classify(None, 1.0)[0] == "unavailable"
    assert classify(1.0, None)[0] == "unavailable"
    assert classify(0.0, 0.0)[0] == "mixed"


def test_time_range_validated():
    import pytest

    with pytest.raises(ValueError):
        ScanRequest(start="2026-10-12T21:00:00Z", end="2026-10-12T10:00:00Z")
    with pytest.raises(ValueError):
        ScanRequest(start="2026-10-12T09:30:00", end="2026-10-12T10:00:00")


def test_health_and_no_credentials_no_fallback(monkeypatch, tmp_path):
    for name in ["SCHWAB_APP_KEY", "SCHWAB_APP_SECRET"]:
        monkeypatch.delenv(name, raising=False)
    with TestClient(create_app(config_dir=tmp_path)) as client:
        assert client.get("/api/v1/health").json()["provider"] == "schwab"
        response = client.post(
            "/api/v1/scan",
            json={"start": "2026-10-01T13:30:00Z", "end": "2026-10-12T20:00:00Z"},
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "credentials_missing"
        assert "demo" not in response.text.lower()


def test_openapi_and_ws_contract():
    with TestClient(create_app()) as client:
        schema = client.get("/openapi.json").json()
        assert "/api/v1/scan" in schema["paths"]
        assert "ScanSnapshot" in schema["components"]["schemas"]
        with client.websocket_connect("/api/v1/ws") as ws:
            message = ws.receive_json()
            assert message["type"] == "status" and message["schema_version"] == "1.0"
            assert isinstance(message["sequence"], int)


def test_no_runtime_synthetic_generator():
    import app.indicators as engine

    assert not hasattr(engine, "synthetic_data")


def test_future_data_does_not_change_past():
    idx = pd.date_range("2026-10-05 09:30", periods=65, freq="5min", tz=TZ)
    close = 100 + np.sin(np.arange(65) / 3) + np.arange(65) * 0.05
    data = pd.DataFrame(
        {
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 100 + np.arange(65) ** 2,
        },
        index=idx,
    )
    original = oscillators(data, data, data)
    changed = data.copy()
    changed.iloc[45:, 0:4] *= 2
    updated = oscillators(changed, data, data)
    pd.testing.assert_frame_equal(original.iloc[:45], updated.iloc[:45])
