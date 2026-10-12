"""Causal features and next-open intraday labels for offline research."""

import json
from pathlib import Path
import warnings
import numpy as np
import pandas as pd
from app.indicators import (
    COLS,
    TZ,
    PARAMS,
    aligned_grid,
    oscillators,
    market_state,
    sector_strength,
    ema,
    wa,
    tr,
)
from research.fetch import ROOT, START, END
from research.universe import SECTORS, COLD_STOCKS


def stock_features(stock, benchmark, proxy, sector, market, sector_name):
    f = oscillators(stock, benchmark, proxy)
    f = f.join(sector_strength(sector, benchmark))
    f = f.join(market[["regime", "efficiency", "ready"]].add_prefix("market_"))
    for name, source in [("stock", stock), ("market", benchmark), ("sector", sector)]:
        for bars in [1, 3, 6, 12]:
            f[f"{name}_return_{bars * 5}m_bp"] = (
                source.close / source.close.shift(bars) - 1
            ) * 10000
    for bars in [3, 6, 12]:
        f[f"stock_minus_market_{bars * 5}m_bp"] = (
            f[f"stock_return_{bars * 5}m_bp"] - f[f"market_return_{bars * 5}m_bp"]
        )
        f[f"stock_minus_sector_{bars * 5}m_bp"] = (
            f[f"stock_return_{bars * 5}m_bp"] - f[f"sector_return_{bars * 5}m_bp"]
        )
    fast, slow = ema(stock.close, 8), ema(stock.close, 21)
    f["ema8_gap_bp"] = (stock.close / fast - 1) * 10000
    f["ema21_gap_bp"] = (stock.close / slow - 1) * 10000
    f["ema8_21_gap_bp"] = (fast / slow - 1) * 10000
    f["ema8_slope_15m_bp"] = (fast / fast.shift(3) - 1) * 10000
    f["stock_atr_bp"] = wa(tr(stock), 14) / stock.close * 10000
    f["market_atr_bp"] = wa(tr(benchmark), 14) / benchmark.close * 10000
    span = (stock.high - stock.low).replace(0, np.nan)
    f["candle_body_fraction"] = (stock.close - stock.open) / span
    f["candle_close_position"] = (stock.close - stock.low) / span
    volume_mean = stock.volume.rolling(20, min_periods=20).mean().replace(0, np.nan)
    f["relative_own_volume"] = (stock.volume / volume_mean).clip(0, 20)
    f["rrs_change"] = f.rrs.diff()
    rule_features = []
    for length in [8, 12, 20]:
        rrs = (
            f.rrs
            if length == 12
            else oscillators(stock, benchmark, proxy, {**PARAMS, "length": length}).rrs
        )
        direction = pd.Series(
            np.select(
                [(rrs > 0) & (rrs > rrs.shift()), (rrs < 0) & (rrs < rrs.shift())],
                [1, -1],
                default=0,
            ),
            index=f.index,
        )
        run = direction.groupby(direction.ne(direction.shift()).cumsum()).cumcount() + 1
        for suffix, values in [
            ("value", rrs),
            ("direction", direction),
            ("run", run.where(direction != 0, 0)),
        ]:
            name = f"rrs{length}_{suffix}"
            f[name] = values
            rule_features.append(name)
    f["decision_minutes_after_open"] = (
        stock.index.hour * 60 + stock.index.minute + 5 - 555
    )
    # Transformations use only the first bar observed so far in the session.
    stock_dates, market_dates = stock.index.normalize(), benchmark.index.normalize()
    session_open = (
        stock.open.where(stock.open.notna().groupby(stock_dates).cumsum().eq(1))
        .groupby(stock_dates)
        .ffill()
    )
    market_open = (
        benchmark.open.where(
            benchmark.open.notna().groupby(market_dates).cumsum().eq(1)
        )
        .groupby(market_dates)
        .ffill()
    )
    f["stock_session_return_bp"] = (stock.close / session_open - 1) * 10000
    f["market_session_return_bp"] = (benchmark.close / market_open - 1) * 10000
    for name in SECTORS:
        f["sector_" + name.replace(" ", "_")] = float(name == sector_name)
    # The retrospective sector event flags are not model inputs. Keep a small,
    # explicit feature set so every input can be tested for prefix invariance.
    keep = [
        name for name in f if name.endswith("_bp") or name.startswith("sector_NIFTY_")
    ]
    keep += [
        "rrs",
        "rrv",
        "rel_volatility",
        "rrs_change",
        "sector_rrs",
        "sector_state",
        "market_regime",
        "market_efficiency",
        "market_ready",
        "relative_own_volume",
        "candle_body_fraction",
        "candle_close_position",
        "decision_minutes_after_open",
    ]
    keep += rule_features
    return f[keep].astype(float).replace([np.inf, -np.inf], np.nan)


def forward_labels(stock, bars):
    """Signal after bar i closes; buy/sell next open, exit h bars later."""
    index = stock.index
    dates = pd.Series(index.date, index=index)
    stamps = pd.Series(index, index=index)
    valid = stock[COLS[:4]].notna().all(axis=1)
    path = valid.rolling(bars + 1, min_periods=bars + 1).sum().shift(-bars).eq(bars + 1)
    same_session = dates.eq(dates.shift(-bars))
    consecutive = (stamps.shift(-bars) - stamps).eq(pd.Timedelta(minutes=bars * 5))
    returns = (stock.close.shift(-bars) / stock.open.shift(-1) - 1) * 10000
    return returns.where(path & same_session & consecutive)


def build():
    report = json.loads((ROOT / "fetch_report.json").read_text())
    if report["failures"]:
        raise RuntimeError("Historical collection has unresolved source failures")
    sources = {
        name: pd.read_pickle(ROOT / (name.replace(" ", "_") + ".pkl"))
        for name in report["instruments"]
    }
    daily = pd.read_pickle(ROOT / "daily.pkl")
    aligned, diagnostics = aligned_grid(
        sources, asof=END, session_profile="nse_cas", start=START, end=END
    )
    benchmark, proxy = aligned["NIFTY 50"], aligned["NIFTYBEES"]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        market = market_state(benchmark, daily)
        frames = []
        audit = {
            "causal_prefix_checks": 0,
            "sources": report["instruments"],
            "diagnostics": diagnostics,
        }
        for sector_name, symbols in SECTORS.items():
            sector = aligned[sector_name]
            for symbol in symbols:
                stock = aligned[symbol]
                f = stock_features(stock, benchmark, proxy, sector, market, sector_name)
                # Warmup and gaps must be past-only, rather than selected using
                # whether a future prediction turns out to be correct.
                ready = (
                    stock[COLS[:4]].notna().all(axis=1)
                    & benchmark[COLS[:4]].notna().all(axis=1)
                    & sector[COLS[:4]].notna().all(axis=1)
                )
                ready = ready.rolling(15, min_periods=15).sum().eq(15)
                ready &= f.decision_minutes_after_open >= 30
                ready &= stock.index >= pd.Timestamp("2025-10-01", tz=TZ)
                for cutoff in np.linspace(500, len(stock) - 100, 4, dtype=int):
                    stop = cutoff + 1
                    prefix_market = market_state(
                        benchmark.iloc[:stop],
                        daily[
                            daily.index.normalize() < stock.index[cutoff].normalize()
                        ],
                    )
                    prefix = stock_features(
                        stock.iloc[:stop],
                        benchmark.iloc[:stop],
                        proxy.iloc[:stop],
                        sector.iloc[:stop],
                        prefix_market,
                        sector_name,
                    )
                    pd.testing.assert_frame_equal(prefix, f.iloc[:stop])
                    audit["causal_prefix_checks"] += 1
                for horizon in [15, 30, 60]:
                    target = forward_labels(stock, horizon // 5)
                    selected = ready & target.notna()
                    part = f.loc[selected].copy()
                    part["return_bp"] = target.loc[selected]
                    part["class_label"] = np.select(
                        [part.return_bp < -10, part.return_bp > 10], [0, 2], default=1
                    )
                    part["symbol"] = symbol
                    part["sector"] = sector_name
                    part["cold_stock"] = symbol in COLD_STOCKS
                    part["date"] = part.index.strftime("%Y-%m-%d")
                    part["decision_time"] = part.index + pd.Timedelta(minutes=5)
                    part["horizon_minutes"] = horizon
                    part["position"] = np.flatnonzero(selected)
                    part["rrs_direction"] = np.select(
                        [
                            (f.rrs > 0) & (f.rrs > f.rrs.shift()),
                            (f.rrs < 0) & (f.rrs < f.rrs.shift()),
                        ],
                        [1, -1],
                        default=0,
                    )[selected]
                    part["momentum_direction"] = (
                        np.sign(f.stock_return_15m_bp.loc[selected])
                        .fillna(0)
                        .astype(int)
                    )
                    part["ema_direction"] = (
                        np.sign(f.ema8_21_gap_bp.loc[selected]).fillna(0).astype(int)
                    )
                    frames.append(part.reset_index(names="bar_time"))
                print(f"Features/labels: {symbol}, prefix checks passed", flush=True)
    data = pd.concat(frames, ignore_index=True)
    data[data.date < "2026-06-01"].to_pickle(ROOT / "development.pkl")
    data[(data.date >= "2026-06-01") & (data.date < "2026-08-01")].to_pickle(
        ROOT / "selection.pkl"
    )
    data[data.date >= "2026-08-03"].to_pickle(ROOT / "test.pkl")
    audit["dataset_rows"] = len(data)
    audit["sessions"] = int(data.date.nunique())
    audit["stock_sessions"] = int(data[["symbol", "date"]].drop_duplicates().shape[0])
    audit["features"] = list(f.columns)
    (ROOT / "dataset_audit.json").write_text(json.dumps(audit, indent=2))
    print(f"Dataset saved: {len(data):,} labeled observations", flush=True)


if __name__ == "__main__":
    build()
