"""Opt-in Groww historical validation. Never calls live-feed or trading APIs.

Run from the repository root with PYTHONPATH=backend .venv/bin/python
backend/validate_history.py. Credentials must already be injected in the process.
Artifacts contain market data and validation results, never tokens or SDK errors.
"""

import csv
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import warnings
import zipfile
from datetime import datetime, timezone

import pandas as pd
from fastapi.testclient import TestClient

from app.contracts import ScanRequest
from app.indicators import COLS, TZ, candle_timestamp, parse_candles
from app.main import create_app
from app.provider import GrowwProvider
from app.sessions import continuous_grid, continuous_mask

ROOT = Path(__file__).resolve().parents[1]
START = pd.Timestamp("2026-09-22 09:15", tz=TZ)
END = pd.Timestamp("2026-10-12 15:30", tz=TZ)


class HistoricalAPI:
    """Expose only the historical method and constants to the application."""

    CANDLE_INTERVAL_MIN_5 = "5minute"
    CANDLE_INTERVAL_DAY = "1day"

    def __init__(self, sdk):
        self._sdk = sdk
        self.calls = []
        self.initial = {}

    def get_historical_candles(self, **kwargs):
        record = dict(kwargs)
        self.calls.append(record)
        try:
            response = self._sdk.get_historical_candles(**kwargs, timeout=30)
        except Exception as error:
            # SDK exceptions may include credentials. Retain only the type.
            record["error_type"] = type(error).__name__
            raise RuntimeError(
                "Historical request failed; SDK details suppressed"
            ) from None
        payload = response.get("payload", response)
        record["returned_rows"] = len(payload["candles"])
        key = (kwargs["groww_symbol"], kwargs["candle_interval"])
        self.initial.setdefault(key, {"candles": payload["candles"]})
        return response


def ranges(index):
    groups = []
    for stamp in sorted(index):
        if not groups or stamp - groups[-1][-1] != pd.Timedelta(minutes=5):
            groups.append([])
        groups[-1].append(stamp)
    return [
        {
            "first_ist": group[0].isoformat(),
            "last_ist": group[-1].isoformat(),
            "bars": len(group),
        }
        for group in groups
    ]


def validate(output):
    from growwapi import GrowwAPI

    assert os.getenv("GROWW_ACCESS_TOKEN"), "GROWW_ACCESS_TOKEN is not configured"
    assert END <= pd.Timestamp.now(tz=TZ), "Requested session has not completed"
    output.mkdir(parents=True, exist_ok=False)
    config = output / "config"
    config.mkdir()
    instruments = json.loads((ROOT / "config/instruments.json").read_text())
    wanted = {"TCS", "NIFTY 50", "NIFTYBEES", "NIFTY IT"}
    instruments = [item for item in instruments if item["symbol"] in wanted]
    assert {item["symbol"] for item in instruments} == wanted
    assert all(
        item.get("groww_symbol") and item.get("exchange_token") for item in instruments
    )
    (config / "instruments.json").write_text(json.dumps(instruments))
    scanner = json.loads((ROOT / "config/scanner.json").read_text())
    scanner["live_enabled"] = False
    (config / "scanner.json").write_text(json.dumps(scanner))
    api = HistoricalAPI(GrowwAPI(os.environ["GROWW_ACCESS_TOKEN"]))
    app = create_app(config)
    workspace = app.state.workspace
    workspace.provider = GrowwProvider(output / "cache")
    workspace.provider.api = api
    request = ScanRequest(
        start=START.to_pydatetime(), end=END.to_pydatetime(), live=False
    )
    report = {
        "request": request.model_dump(mode="json"),
        "calls": api.calls,
        "status": "failed",
    }
    try:
        with TestClient(app) as client:
            snapshot = workspace.scan(request)
            chart = workspace.charts["TCS"]
            row = next(row for row in snapshot.rows if row.symbol == "TCS")
            assert chart.quality == row
            assert (
                row.close == chart.points[-1].close
                and row.candle_time == chart.points[-1].time
            )
            assert row.rrs == chart.points[-1].features["rrs"]
            assert row.previous_rrs == chart.points[-2].features["rrs"]
            assert row.rrv == chart.points[-1].features["rrv"]
            assert (
                row.relative_volatility == chart.points[-1].features["rel_volatility"]
            )
            assert workspace.feed is None and workspace.feed_state == "disabled"
            assert row.sector_rrs == chart.points[-1].features["sector_rrs"]
            assert row.sector_state == chart.points[-1].features["sector_state"]
            assert row.market_regime == chart.points[-1].features["market_regime"]
            assert not snapshot.diagnostics["fetch_failures"]
            run = workspace.export_run
            final = run.inputs["TCS"]
            assert continuous_mask(final.index, "nse_cas").all()
            raw = api.initial[("NSE-TCS", "5minute")]
            baseline = parse_candles(
                raw,
                now=END,
                instrument="TCS",
                session_profile="nse_cas",
                allow_unusable=True,
            )
            baseline = baseline.reindex(final.index)
            raw_missing = baseline[COLS[:4]].isna().any(axis=1)
            final_missing = final[COLS[:4]].isna().any(axis=1)
            recovered = final.index[raw_missing & ~final_missing]
            unresolved = final.index[final_missing]
            baseline.to_csv(output / "initial_TCS.csv", na_rep="")
            final.to_csv(output / "recovered_TCS.csv", na_rep="")
            sessions = []
            for day in sorted(set(final.index.date)):
                mask = final.index.date == day
                sessions.append(
                    {
                        "date": str(day),
                        "slots": int(mask.sum()),
                        "initial_missing_ohlc": int(raw_missing[mask].sum()),
                        "final_missing_ohlc": int(final_missing[mask].sum()),
                        "recovered": ranges(recovered[recovered.date == day]),
                        "remaining": ranges(unresolved[unresolved.date == day]),
                    }
                )
            # Explicitly report outage-session coverage, without inferring holidays.
            outage = continuous_grid([pd.Timestamp("2026-09-29", tz=TZ)], "nse_cas")
            report["september_29_observed"] = bool(final.index.isin(outage).any())
            report["sessions"] = sessions
            report["tcs_gap_recovery"] = final.attrs.get("gap_recovery", {})
            report["parser_diagnostics"] = final.attrs.get("parser_diagnostics", {})
            response = client.get(
                "/api/v1/exports/TCS.csv", params={"run_id": chart.run_id}
            )
            response.raise_for_status()
            csv_rows = list(
                csv.DictReader(io.StringIO(response.content.decode("utf-8-sig")))
            )
            assert len(csv_rows) == len(chart.points)
            for exported, point in zip(csv_rows, chart.points):
                for field in COLS:
                    expected = getattr(point, field)
                    assert (
                        exported[field] == ""
                        if expected is None
                        else float(exported[field]) == expected
                    )
                for field in ("rrs", "rrv", "rel_volatility"):
                    expected = point.features[field]
                    assert (
                        exported[field] == ""
                        if expected is None
                        else float(exported[field]) == expected
                    )
            (output / "TCS.csv").write_bytes(response.content)
            response = client.get(
                "/api/v1/exports/run.zip", params={"run_id": chart.run_id}
            )
            response.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
                manifest = json.loads(bundle.read("manifest.json"))
                for path, digest in manifest["file_sha256"].items():
                    assert hashlib.sha256(bundle.read(path)).hexdigest() == digest
                assert (
                    bundle.read("results/TCS.csv") == (output / "TCS.csv").read_bytes()
                )
                assert manifest["result_rows"]["TCS"] == len(chart.points)
                assert manifest["request"]["live"] is False
                normalized = list(
                    csv.DictReader(
                        io.StringIO(
                            bundle.read(manifest["input_files"]["TCS"]).decode(
                                "utf-8-sig"
                            )
                        )
                    )
                )
                assert len(normalized) == len(final)
                assert sum(row["close"] == "" for row in normalized) == int(
                    final_missing.sum()
                )
            (output / "run.zip").write_bytes(response.content)
            before = len(api.calls)
            workspace.scan(request)
            repeat_calls = api.calls[before:]
            assert all(call["candle_interval"] == "5minute" for call in repeat_calls)
            # Immutable baseline/daily cache must be reused; unresolved ranges can retry.
            assert all(
                not (
                    call["start_time"] == START.strftime("%Y-%m-%d %H:%M:%S")
                    and call["end_time"] == END.strftime("%Y-%m-%d %H:%M:%S")
                )
                for call in repeat_calls
            )
            pd.testing.assert_frame_equal(final, workspace.export_run.inputs["TCS"])
            report["cache_repeat_calls"] = repeat_calls
            # Controlled cache holes are distinct from genuine broker outages.
            # Remove known-good rows only in a disposable copy of our own cache.
            controlled_cache = output / "controlled-cache"
            shutil.copytree(output / "cache", controlled_cache)
            key = hashlib.sha256(
                f"NSE-TCS|{START}|{END}|5|nse_cas|v3".encode()
            ).hexdigest()
            cache_file = controlled_cache / f"{key}.json"
            cached = json.loads(cache_file.read_text())
            payload = cached.get("payload", cached)
            removed = pd.date_range("2026-09-28 10:00", periods=3, freq="5min", tz=TZ)
            assert final.loc[removed, COLS].notna().all().all()
            original_rows = payload["candles"]
            payload["candles"] = [
                r for r in original_rows if candle_timestamp(r[0]) not in removed
            ]
            assert len(original_rows) - len(payload["candles"]) == 3
            cache_file.write_text(json.dumps(cached))
            controlled = GrowwProvider(controlled_cache)
            controlled.api = api
            instrument = next(
                item for item in workspace.instruments if item.symbol == "TCS"
            )
            before = len(api.calls)
            repaired = controlled.fetch(instrument, START, END)
            pd.testing.assert_frame_equal(repaired, final)
            assert repaired.attrs["gap_recovery"]["recovered_price_bars"] == 3
            assert repaired.attrs["gap_recovery"]["remaining_price_gaps"] == int(
                final_missing.sum()
            )
            report["controlled_cache_recovery"] = {
                "purpose": "Deliberately removed available candles; not natural outage recovery",
                "removed_ist": [stamp.isoformat() for stamp in removed],
                "gap_recovery": repaired.attrs["gap_recovery"],
                "calls": api.calls[before:],
            }
            before = len(api.calls)
            persisted = controlled.fetch(instrument, START, END)
            pd.testing.assert_frame_equal(persisted, final)
            assert persisted.attrs["gap_recovery"]["recovered_price_bars"] == 0
            assert all(
                call["start_time"] != "2026-09-28 10:00:00"
                for call in api.calls[before:]
            )
            report["controlled_cache_recovery"]["persisted_repair_reused"] = True
            report["checks"] = [
                "historical-only API",
                "continuous session filtering",
                "scanner/chart equality",
                "CSV values/nulls",
                "ZIP content/checksums",
                "immutable cache reuse",
            ]
            report["status"] = "passed"
    except Exception as error:
        report["error_type"] = type(error).__name__
        # Do not print or persist exception messages, headers, or tokens.
        raise RuntimeError(
            "Historical validation failed; inspect sanitized report"
        ) from None
    finally:
        (output / "report.json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    output = (
        ROOT
        / "data/historical-validation"
        / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            validate(output)
    except Exception as error:
        print(
            f"Validation failed ({type(error).__name__}); sanitized artifacts: {output}"
        )
        sys.exit(1)
    print(f"Historical validation passed; artifacts: {output}")
