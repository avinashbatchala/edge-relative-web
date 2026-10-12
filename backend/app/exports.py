"""Lossless run exports from captured normalized inputs and calculated chart values."""

import csv
import hashlib
import io
import json
import math
import re
import sys
import numpy as np
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from .contracts import ChartResponse, ScanSnapshot
from .indicators import COLS, TZ
from .scanner import classify, number

EXPORT_VERSION = "2.0"
OSCILLATORS = ["rrs", "rrv", "rel_volatility"]
SECTOR_FEATURES = [
    "sector_rrs",
    "sector_fast",
    "sector_slow",
    "sector_confirmed_rrs",
    "sector_state",
    "sector_bull_count",
    "sector_bear_count",
    "sector_new_strong",
    "sector_new_weak",
]
MARKET_FEATURES = [
    "swing_high",
    "previous_high",
    "swing_low",
    "previous_low",
    "regime",
    "bias",
    "phase",
    "efficiency",
    "ready",
    "daily_bull",
    "daily_bear",
    "m5_bull",
    "m5_bear",
    "confirmed_bull",
    "confirmed_bear",
    "bull_count",
    "bear_count",
    "new_bull",
    "new_bear",
    "new_dislocation",
    "entry_status",
]
FEATURES = (
    [
        key
        for study in OSCILLATORS
        for key in [
            study,
            study + "_corr",
            study + "_bull_event",
            study + "_bear_event",
        ]
    ]
    + SECTOR_FEATURES
    + ["market_" + key for key in MARKET_FEATURES]
    + ["price_ema8", "price_ema21"]
)
PHASES = {
    0: "Unavailable/neutral",
    1: "Bull impulse",
    2: "Bull pullback",
    3: "Bear impulse",
    4: "Bear pullback",
    5: "Compression",
}


def json_bytes(value):
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def safe_filename(symbol):
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", symbol).strip(".") or "instrument"
    if safe != symbol:
        safe += "_" + hashlib.sha256(symbol.encode()).hexdigest()[:8]
    return safe


def csv_cell(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return value if math.isfinite(value) else ""
    text = str(value)
    # Prevent text fields from becoming spreadsheet formulas. Numeric negatives stay numeric.
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r")):
        return "'" + text
    return text


def csv_bytes(columns, rows):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([csv_cell(row.get(column)) for column in columns])
    # BOM allows spreadsheet apps to recognize UTF-8; readers may use utf-8-sig.
    return output.getvalue().encode("utf-8-sig")


def timestamps(epoch):
    stamp = pd.Timestamp(epoch, unit="s", tz="UTC")
    local = stamp.tz_convert(TZ)
    return {
        "epoch_seconds": epoch,
        "timestamp_utc": stamp.isoformat(),
        "timestamp_ist": local.isoformat(),
        "session_date": str(local.date()),
    }


def frame_csv(frame):
    rows = []
    for stamp, row in frame.iterrows():
        rows.append(
            {**timestamps(int(stamp.timestamp())), **{c: number(row[c]) for c in COLS}}
        )
    return csv_bytes(
        ["epoch_seconds", "timestamp_utc", "timestamp_ist", "session_date", *COLS], rows
    )


@dataclass(frozen=True)
class ExportRun:
    run_id: str
    charts: dict[str, ChartResponse]
    snapshot: ScanSnapshot
    request: dict
    inputs: dict[str, pd.DataFrame]
    daily: pd.DataFrame | None
    instruments: list[dict]
    source_files: dict[str, bytes]

    @classmethod
    def capture(cls, charts, snapshot, request, inputs, daily, instruments, run_id):
        # Inputs/calculated charts are newly allocated per scan and never mutated afterward.
        # Keep one complete run, not an accumulating history or a second calculation engine.
        return cls(
            run_id,
            dict(charts),
            snapshot,
            request.model_dump(mode="json"),
            dict(inputs),
            daily,
            [item.model_dump(mode="json") for item in instruments],
            {
                name: (Path(__file__).parent / name).read_bytes()
                for name in [
                    "indicators.py",
                    "scanner.py",
                    "service.py",
                    "exports.py",
                    "contracts.py",
                ]
            },
        )

    def csv(self, symbol):
        chart = self.charts[symbol]
        features = sorted(
            set(FEATURES).union(key for point in chart.points for key in point.features)
        )
        rows = []
        previous = None
        code_hashes = {
            name: hashlib.sha256(content).hexdigest()
            for name, content in self.source_files.items()
        }
        source_names = {
            "price_benchmark": chart.price_benchmark,
            "volume_benchmark": chart.volume_benchmark,
            "sector_benchmark": chart.sector_benchmark,
        }
        for point in chart.points:
            f = point.features
            row = {
                "export_schema_version": EXPORT_VERSION,
                "run_id": self.run_id,
                "symbol": symbol,
                "provider": "groww",
                "interval_minutes": 5,
                "price_unit": chart.price_unit,
                "volume_unit": chart.volume_unit,
                "is_provisional": False,
                "is_closed": True,
                **timestamps(point.time),
                "candle_end_utc": pd.Timestamp(
                    point.time + 300, unit="s", tz="UTC"
                ).isoformat(),
                **{c: getattr(point, c) for c in COLS},
                "price_valid": all(getattr(point, c) is not None for c in COLS[:4]),
                "volume_available": point.volume is not None and point.volume >= 0,
                "snapshot_quality": chart.quality.quality,
                "snapshot_direction": chart.quality.direction,
                "snapshot_reasons_json": json.dumps(
                    chart.quality.reasons, ensure_ascii=False
                ),
                "scan_generated_at": self.snapshot.generated_at.isoformat(),
                "requested_start": self.request["start"],
                "requested_end": self.request["end"],
                "indicator_code_sha256": code_hashes["indicators.py"],
                "scanner_code_sha256": code_hashes["scanner.py"],
                "scanner_settings_json": json.dumps(
                    {
                        key: self.request[key]
                        for key in [
                            "market_filter",
                            "sector_filter",
                            "volume_filter",
                            "min_volume_momentum",
                        ]
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "parameters_json": json.dumps(
                    chart.parameters, sort_keys=True, separators=(",", ":")
                ),
                **{key: f.get(key) for key in features},
            }
            for study in OSCILLATORS:
                current = number(f.get(study))
                prior = number(previous.features.get(study)) if previous else None
                available = current is not None and prior is not None
                direction, _ = classify(current, prior)
                row[study + "_available"] = current is not None
                row[study + "_previous"] = prior
                row[study + "_direction"] = direction
                row[study + "_strength"] = direction == "bullish" if available else None
                row[study + "_weakness"] = direction == "bearish" if available else None
                row[study + "_rising"] = current > prior if available else None
                row[study + "_falling"] = current < prior if available else None
            ready = f.get("market_ready") is True
            regime = number(f.get("market_regime"))
            sector = number(f.get("sector_state"))
            row["market_state_label"] = (
                chart.regime_labels.get(str(int(regime)), "Unavailable")
                if ready and regime is not None
                else "Unavailable"
            )
            row["market_phase_label"] = PHASES.get(
                int(f.get("market_phase") or 0), "Unavailable/neutral"
            )
            row["market_dislocation"] = regime == 4 if ready else None
            row["sector_state_label"] = {1: "Strong", -1: "Weak", 0: "Neutral"}.get(
                sector, "Unavailable"
            )
            row["sector_strong"] = sector == 1 if sector is not None else None
            row["sector_weak"] = sector == -1 if sector is not None else None
            row["row_quality"] = (
                "missing_price"
                if not row["price_valid"]
                else "warmup_or_gap" if not row["rrs_available"] else "ready"
            )
            for role, name in source_names.items():
                row[role] = name
                frame = self.inputs.get(name)
                stamp = pd.Timestamp(point.time, unit="s", tz="UTC").tz_convert(TZ)
                source = (
                    frame.loc[stamp]
                    if frame is not None and stamp in frame.index
                    else {}
                )
                for column in COLS:
                    row[role + "_" + column] = number(source.get(column))
            rows.append(row)
            previous = point
        columns = (
            list(rows[0])
            if rows
            else [
                "export_schema_version",
                "run_id",
                "symbol",
                "epoch_seconds",
                *COLS,
                *features,
            ]
        )
        return csv_bytes(columns, rows)

    def dictionary(self):
        columns = {
            key: {
                "description": "Calculated Python feature; preserved exactly from ChartPoint.features. See bundled engine source.",
                "nullable": True,
            }
            for key in FEATURES
        }
        for study in OSCILLATORS:
            columns[study] = {
                "description": {
                    "rrs": "Rolling stock-vs-price-benchmark ATR-normalized relative strength.",
                    "rrv": "Relative volume momentum against the traded volume proxy; not time-of-day RVOL.",
                    "rel_volatility": "Relative underlying ATR expansion; not implied volatility or volume-expansion RVE.",
                }[study],
                "unit": "dimensionless",
                "nullable": True,
            }
            columns[study + "_corr"] = {
                "description": "Rolling correlation of the study input series.",
                "unit": "correlation coefficient",
                "nullable": True,
            }
            for side in ["bull", "bear"]:
                columns[study + "_" + side + "_event"] = {
                    "description": "Original lagged event flag: condition on preceding bar became true relative to the bar before it. Event timestamp is the observation bar, not a shifted execution fill.",
                    "nullable": True,
                }
            columns[study + "_strength"] = {
                "description": "Current value positive and rising versus immediately preceding aligned bar; null if either value is missing. Not a trade authorization.",
                "nullable": True,
            }
            columns[study + "_weakness"] = {
                "description": "Current value negative and falling versus immediately preceding aligned bar; null if either value is missing. Not a trade authorization.",
                "nullable": True,
            }
            for suffix in ["available", "previous", "direction", "rising", "falling"]:
                columns[study + "_" + suffix] = {
                    "description": "Availability or immediate-previous-bar comparison for "
                    + study
                    + ". Gaps are never skipped.",
                    "nullable": True,
                }
        columns.update(
            {
                "epoch_seconds": {
                    "description": "UTC epoch seconds identifying the beginning of a completed 5-minute interval."
                },
                "timestamp_ist": {
                    "description": "Same candle beginning in Asia/Kolkata with explicit +05:30 offset."
                },
                "is_closed": {
                    "description": "All exported rows are completed interval slots; missing prices may still be null."
                },
                "is_provisional": {
                    "description": "Always false. Live LTP quotes are never included."
                },
                "row_quality": {
                    "description": "Per-row price/RRS availability: missing_price, warmup_or_gap, or ready. Not an all-study validity assessment."
                },
                "snapshot_quality": {
                    "description": "Latest scanner freshness/quality at capture, repeated as run context; not the historical quality of each row."
                },
                "snapshot_direction": {
                    "description": "Latest scanner classification with request filters, repeated as run context; not a per-row trading signal."
                },
                "market_dislocation": {
                    "description": "Current ready market regime equals 4; null when market context is unready."
                },
                "market_new_dislocation": {
                    "description": "Original transition into a ready dislocation regime; distinct from its ongoing state."
                },
                "sector_state": {
                    "description": "1 strong, -1 weak, 0 neutral, null unavailable; original confirmation rules apply."
                },
                "sector_new_strong": {
                    "description": "Original confirmed sector-strength transition after eligibility/blackout gates."
                },
                "sector_new_weak": {
                    "description": "Original confirmed sector-weakness transition after eligibility/blackout gates."
                },
            }
        )
        for chart in self.charts.values():
            header = next(
                csv.reader(io.StringIO(self.csv(chart.symbol).decode("utf-8-sig")))
            )
            for key in header:
                columns.setdefault(
                    key,
                    {
                        "description": "Run metadata, named source OHLCV, or preserved feature; source identity is given by its benchmark column.",
                        "nullable": True,
                    },
                )
        return {
            "export_schema_version": EXPORT_VERSION,
            "encoding": "UTF-8 with BOM for CSV",
            "null": "Empty CSV field / JSON null",
            "boolean": "true / false; missing is empty",
            "formula_safety": "Potential spreadsheet formula text is apostrophe-prefixed; numeric negatives remain numeric.",
            "regime_labels": (
                next(iter(self.charts.values())).regime_labels if self.charts else {}
            ),
            "phase_labels": PHASES,
            "columns": columns,
        }

    def bundle(self):
        files = {
            f"results/{safe_filename(symbol)}.csv": self.csv(symbol)
            for symbol in sorted(self.charts)
        }
        input_files = {}
        for name, frame in sorted(self.inputs.items()):
            path = f"inputs/{safe_filename(name)}_5m.csv"
            files[path] = frame_csv(frame)
            input_files[name] = path
        if self.daily is not None:
            files["inputs/benchmark_daily.csv"] = frame_csv(self.daily)
        files["diagnostics.json"] = json_bytes(self.snapshot.diagnostics)
        files["scanner_snapshot.json"] = json_bytes(
            self.snapshot.model_dump(mode="json")
        )
        files["data_dictionary.json"] = json_bytes(self.dictionary())
        code_hashes = {}
        for name, code in self.source_files.items():
            files["engine/" + name] = code
            code_hashes[name] = hashlib.sha256(code).hexdigest()
        manifest = {
            "export_schema_version": EXPORT_VERSION,
            "run_id": self.run_id,
            "provider": "groww",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "scan_generated_at": self.snapshot.generated_at.isoformat(),
            "request": self.request,
            "instruments": self.instruments,
            "interval_minutes": 5,
            "timezone": TZ,
            "price_benchmark": self.snapshot.price_benchmark,
            "volume_benchmark": self.snapshot.volume_benchmark,
            "parameters_by_symbol": {s: c.parameters for s, c in self.charts.items()},
            "input_files": input_files,
            "daily_context_file": (
                "inputs/benchmark_daily.csv" if self.daily is not None else None
            ),
            "result_rows": {s: len(c.points) for s, c in self.charts.items()},
            "source_code_sha256": code_hashes,
            "runtime_versions": {
                "python": sys.version.split()[0],
                "pandas": pd.__version__,
                "numpy": np.__version__,
            },
            "file_sha256": {
                path: hashlib.sha256(content).hexdigest()
                for path, content in sorted(files.items())
            },
            "scope": "Full loaded run, independent of chart zoom, pane visibility, and replay cursor. Normalized inputs retain gaps/quarantined prices as null. No quotes or credentials.",
            "known_limits": [
                "Regular NSE sessions only; no authoritative holiday calendar or corporate-action adjustments.",
                "Reproduces this Python port, not guaranteed Thinkorswim prefetch parity.",
                "Snapshot freshness flags are run context, not historical per-row validity.",
            ],
        }
        files["manifest.json"] = json_bytes(manifest)
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for path, content in sorted(files.items()):
                archive.writestr(path, content)
        return output.getvalue()
