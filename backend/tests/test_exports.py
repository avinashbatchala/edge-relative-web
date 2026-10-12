import csv
import io
import json
import zipfile
from fastapi.testclient import TestClient
from app.main import create_app
from app.contracts import ScanRequest
from test_workspace import FixtureProvider, workspace

REQUEST = ScanRequest(start="2026-08-03T03:45:00Z", end="2026-08-06T10:00:00Z")


def scanned_app(tmp_path):
    workspace(tmp_path)  # Writes a test-only instrument catalog.
    app = create_app(tmp_path)
    app.state.workspace.provider = FixtureProvider()
    app.state.workspace.scan(REQUEST)
    return app


def test_csv_download_contains_inputs_signals_and_provenance(tmp_path):
    app = scanned_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/v1/exports/TCS.csv")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert "attachment" in response.headers["content-disposition"]
        rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
        last = rows[-1]
        chart = app.state.workspace.charts["TCS"]
        for field in [
            "symbol",
            "run_id",
            "timestamp_utc",
            "timestamp_ist",
            "session_date",
            "rrs",
            "rrv",
            "rel_volatility",
            "rrs_corr",
            "sector_new_strong",
            "sector_new_weak",
            "market_new_dislocation",
            "market_confirmed_bull",
            "market_confirmed_bear",
            "rrs_strength",
            "rrs_weakness",
            "market_dislocation",
            "price_benchmark_close",
            "volume_benchmark_volume",
            "sector_benchmark_close",
            "rrs_available",
            "snapshot_quality",
            "parameters_json",
        ]:
            assert field in last, field
        assert float(last["rrs"]) == chart.points[-1].features["rrs"]
        assert last["run_id"] == chart.run_id
        assert last["timestamp_ist"].endswith("+05:30")
        assert last["is_provisional"] == "false"
        assert len(rows) == len(chart.points)
        assert rows[0]["rrs"] == "" and rows[0]["rrs_available"] == "false"
        assert "NaN" not in response.text


def test_run_bundle_contains_reproducible_input_history_and_manifest(tmp_path):
    app = scanned_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/v1/exports/run.zip")
        assert (
            response.status_code == 200
            and response.headers["content-type"] == "application/zip"
        )
        with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
            manifest = json.loads(bundle.read("manifest.json"))
            assert (
                manifest["provider"] == "groww"
                and manifest["export_schema_version"] == "2.0"
            )
            assert manifest["request"]["start"] == REQUEST.start.isoformat().replace(
                "+00:00", "Z"
            )
            assert "results/TCS.csv" in bundle.namelist()
            assert "inputs/benchmark_daily.csv" in bundle.namelist()
            assert "data_dictionary.json" in bundle.namelist()
            assert "diagnostics.json" in bundle.namelist()
            for path, digest in manifest["file_sha256"].items():
                import hashlib

                assert hashlib.sha256(bundle.read(path)).hexdigest() == digest
            assert manifest["source_code_sha256"]["indicators.py"]
            assert b"GROWW_API_SECRET" not in bundle.read("manifest.json")
            assert (
                "market_new_dislocation"
                in json.loads(bundle.read("data_dictionary.json"))["columns"]
            )


def test_export_without_loaded_run_has_clear_error(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        for path in ["/api/v1/exports/TCS.csv", "/api/v1/exports/run.zip"]:
            response = client.get(path)
            assert (
                response.status_code == 404
                and "history" in response.json()["detail"].lower()
            )


def test_export_rejects_a_superseded_chart_run(tmp_path):
    app = scanned_app(tmp_path)
    first = app.state.workspace.charts["TCS"].run_id
    app.state.workspace.scan(REQUEST)
    with TestClient(app) as client:
        response = client.get("/api/v1/exports/TCS.csv", params={"run_id": first})
        assert response.status_code == 409
        assert "refresh" in response.json()["detail"].lower()


def test_missing_sector_has_stable_null_columns(tmp_path):
    app = scanned_app(tmp_path)
    w = app.state.workspace
    w.instruments[0] = w.instruments[0].model_copy(update={"sector": "UNKNOWN"})
    w.scan(REQUEST)
    with TestClient(app) as client:
        rows = list(
            csv.DictReader(
                io.StringIO(
                    client.get("/api/v1/exports/TCS.csv").content.decode("utf-8-sig")
                )
            )
        )
        assert rows[-1]["sector_new_strong"] == ""
        assert rows[-1]["sector_benchmark_close"] == ""
        assert rows[-1]["sector_state_label"] == "Unavailable"


def test_unknown_symbol_is_not_exported(tmp_path):
    with TestClient(scanned_app(tmp_path)) as client:
        assert client.get("/api/v1/exports/UNKNOWN.csv").status_code == 404


def test_export_preserves_boolean_zero_missing_and_future_features(tmp_path):
    app = scanned_app(tmp_path)
    run = app.state.workspace.export_run
    point = run.charts["TCS"].points[0]
    point.features.update(
        {
            "rrs": 0.0,
            "sector_new_strong": False,
            "market_new_dislocation": True,
            "future_metric": 2.5,
            "unsafe_label": "=1+1",
        }
    )
    rows = list(csv.DictReader(io.StringIO(run.csv("TCS").decode("utf-8-sig"))))
    assert rows[0]["rrs"] == "0.0" and rows[0]["sector_new_strong"] == "false"
    assert (
        rows[0]["market_new_dislocation"] == "true"
        and rows[0]["future_metric"] == "2.5"
    )
    assert rows[1]["future_metric"] == "" and rows[0]["unsafe_label"] == "'=1+1"


def test_captured_run_does_not_change_when_config_or_request_changes(tmp_path):
    app = scanned_app(tmp_path)
    w = app.state.workspace
    run = w.export_run
    before = run.csv("TCS")
    w.parameters["length"] = 99
    w.request = w.request.model_copy(update={"market_filter": True})
    assert run.csv("TCS") == before
    assert run.request["market_filter"] is False


def test_normalized_input_gaps_survive_export(tmp_path):
    app = scanned_app(tmp_path)
    w = app.state.workspace
    original = w.provider.fetch

    def fetch(item, *args, **kwargs):
        data = original(item, *args, **kwargs)
        if item.symbol == "NIFTY 50" and kwargs.get("interval", 5) == 5:
            data.iloc[50] = float("nan")
        return data

    w.provider.fetch = fetch
    w.scan(REQUEST)
    rows = list(
        csv.DictReader(io.StringIO(w.export_run.csv("TCS").decode("utf-8-sig")))
    )
    assert rows[50]["price_benchmark_close"] == "" and rows[50]["rrs"] == ""
    assert rows[50]["rrs_available"] == "false"


def test_export_contract_documents_binary_and_text_content(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        paths = client.get("/openapi.json").json()["paths"]
        assert (
            "text/csv"
            in paths["/api/v1/exports/{symbol}.csv"]["get"]["responses"]["200"][
                "content"
            ]
        )
        assert (
            "application/zip"
            in paths["/api/v1/exports/run.zip"]["get"]["responses"]["200"]["content"]
        )
