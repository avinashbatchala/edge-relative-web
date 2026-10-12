"""Fetch only historical candles, using an already-injected Groww token.

From repository root: PYTHONPATH=backend .venv/bin/python -m research.fetch
"""

import json
import os
from pathlib import Path
import warnings
import pandas as pd
from app.provider import GrowwProvider, ProviderError
from app.indicators import TZ
from research.universe import instruments

ROOT = Path(__file__).resolve().parents[2] / "data/multisector-research"
START = pd.Timestamp("2025-09-01 09:15", tz=TZ)
END = pd.Timestamp("2026-10-12 15:30", tz=TZ)


def run():
    if not os.getenv("GROWW_ACCESS_TOKEN"):
        raise RuntimeError(
            "Configure GROWW_ACCESS_TOKEN securely in environment settings"
        )
    ROOT.mkdir(parents=True, exist_ok=True)
    provider = GrowwProvider(ROOT / "cache")
    report = {
        "start": START.isoformat(),
        "end": END.isoformat(),
        "instruments": {},
        "failures": {},
    }
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for number, item in enumerate(instruments(), 1):
            path = ROOT / (item.symbol.replace(" ", "_") + ".pkl")
            print(f"[{number}/28] Historical candles: {item.symbol}", flush=True)
            try:
                if path.exists():
                    frame = pd.read_pickle(path)
                else:
                    frame = provider.fetch(item, START, END)
                    frame.to_pickle(path)
                if not frame.close.notna().any():
                    raise ValueError("No usable source prices")
                report["instruments"][item.symbol] = {
                    "kind": item.kind,
                    "sector": item.sector,
                    "groww_symbol": item.groww_symbol,
                    "session_profile": item.session_profile,
                    "rows": len(frame),
                    "usable_prices": int(frame.close.notna().sum()),
                    "sessions": len(set(frame.index.date)),
                    "first": frame.index.min().isoformat(),
                    "last": frame.index.max().isoformat(),
                    "gap_recovery": frame.attrs.get("gap_recovery", {}),
                }
                print(
                    f"  {len(frame):,} slots, {report['instruments'][item.symbol]['sessions']} observed sessions",
                    flush=True,
                )
            except Exception as error:
                code = (
                    error.code
                    if isinstance(error, ProviderError)
                    else type(error).__name__
                )
                report["failures"][item.symbol] = code
                print(f"  Failed: {code}; SDK messages suppressed", flush=True)
            (ROOT / "fetch_report.json").write_text(json.dumps(report, indent=2))
        path = ROOT / "daily.pkl"
        try:
            if not path.exists():
                benchmark = next(i for i in instruments() if i.symbol == "NIFTY 50")
                provider.fetch(
                    benchmark, START - pd.Timedelta(days=150), END, interval=1440
                ).to_pickle(path)
        except Exception as error:
            report["failures"]["daily"] = (
                error.code if isinstance(error, ProviderError) else type(error).__name__
            )
    (ROOT / "fetch_report.json").write_text(json.dumps(report, indent=2))
    if report["failures"]:
        raise RuntimeError(
            "Some historical sources failed; inspect sanitized fetch_report.json"
        )
    print("Historical collection complete", flush=True)


if __name__ == "__main__":
    run()
