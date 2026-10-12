import json, math, hashlib, time, html
from pathlib import Path
import numpy as np
import pandas as pd
from .sessions import continuous_mask, continuous_grid

TZ = "Asia/Kolkata"
COLS = ["open", "high", "low", "close", "volume"]
# Small explicit research mapping, not a complete or authoritative constituent database.
SECTORS = {
    "TCS": "NIFTY IT",
    "INFY": "NIFTY IT",
    "WIPRO": "NIFTY IT",
    "HCLTECH": "NIFTY IT",
    "HDFCBANK": "NIFTY BANK",
    "ICICIBANK": "NIFTY BANK",
    "SBIN": "NIFTY BANK",
    "AXISBANK": "NIFTY BANK",
    "KOTAKBANK": "NIFTY BANK",
    "SUNPHARMA": "NIFTY PHARMA",
    "DRREDDY": "NIFTY PHARMA",
    "CIPLA": "NIFTY PHARMA",
    "MARUTI": "NIFTY AUTO",
    "M&M": "NIFTY AUTO",
    "BAJAJ-AUTO": "NIFTY AUTO",
    "HINDUNILVR": "NIFTY FMCG",
    "ITC": "NIFTY FMCG",
    "NESTLEIND": "NIFTY FMCG",
    "TATASTEEL": "NIFTY METAL",
    "JSWSTEEL": "NIFTY METAL",
    "HINDALCO": "NIFTY METAL",
}

PARAMS = dict(
    length=12,
    smoothVol=3,
    useLog=True,
    atrPeriod=14,
    smoothATR=1,
    dailyFastLength=8,
    dailySlowLength=21,
    m5FastLength=8,
    m5SlowLength=21,
    pivotWidth=3,
    efficiencyLength=12,
    trendEfficiencyMin=0.30,
    rangeEfficiencyMax=0.20,
    atrLength=14,
    shockATRMultiplier=3.5,
    shockLookback=6,
    compressionLength=8,
    compressionATRMultiplier=2.0,
    confirmationBars=3,
    sectorFastLength=3,
    sectorSlowLength=8,
    blackout_minutes=30,
)


def validate_params(p):
    integer_keys = [
        "length",
        "smoothVol",
        "atrPeriod",
        "smoothATR",
        "dailyFastLength",
        "dailySlowLength",
        "m5FastLength",
        "m5SlowLength",
        "pivotWidth",
        "efficiencyLength",
        "atrLength",
        "shockLookback",
        "compressionLength",
        "confirmationBars",
        "sectorFastLength",
        "sectorSlowLength",
    ]
    if any(
        not isinstance(p[k], int) or isinstance(p[k], bool) or p[k] < 1
        for k in integer_keys
    ):
        raise ValueError("Lengths must be positive integers")
    if not (
        p["dailySlowLength"] > p["dailyFastLength"]
        and p["m5SlowLength"] > p["m5FastLength"]
        and p["sectorSlowLength"] > p["sectorFastLength"]
        and p["pivotWidth"] >= 2
        and p["efficiencyLength"] >= 2
        and p["compressionLength"] >= 2
        and 0 <= p["rangeEfficiencyMax"] < p["trendEfficiencyMin"] <= 1
        and p["shockATRMultiplier"] > 0
        and p["compressionATRMultiplier"] > 0
        and 0 <= p["blackout_minutes"] < 375
    ):
        raise ValueError("Invalid market-state settings")


def recursive_average(x, n, wilder=False):
    """SMA seed for Wilder; first-value seed for EMA. Reset after any missing observation."""
    out = np.full(len(x), np.nan)
    buf = []
    value = np.nan
    alpha = 1 / n if wilder else 2 / (n + 1)
    for i, v in enumerate(x.to_numpy(dtype=float)):
        if not np.isfinite(v):
            value = np.nan
            buf = []
            continue
        if np.isnan(value):
            if wilder:
                buf.append(v)
                if len(buf) < n:
                    continue
                value = float(np.mean(buf))
            else:
                value = v
        else:
            value = alpha * v + (1 - alpha) * value
        out[i] = value
    return pd.Series(out, index=x.index)


def wa(x, n):
    return recursive_average(x, n, True)


def ema(x, n):
    return recursive_average(x, n)


def tr(d):
    # Requires preceding close: a missing predecessor is not replaced by high-low.
    return pd.concat(
        [
            d.high - d.low,
            (d.high - d.close.shift()).abs(),
            (d.low - d.close.shift()).abs(),
        ],
        axis=1,
    ).max(axis=1, skipna=False)


def positive_ratio(a, b):
    return a.div(b.where(b > 0))


def flag(x):
    return x.astype("boolean").fillna(False).astype(bool)


def transition(x):
    return flag(x) & ~flag(x.shift())


def consecutive(x, n):
    return flag(x).rolling(n, min_periods=n).sum().eq(n)


def oscillators(s, b, v, p=PARAMS):
    out = pd.DataFrame(index=s.index)
    n = p["length"]
    sa = wa(tr(s).shift(), n)
    ba = wa(tr(b).shift(), n)
    # Stronger fail-closed rule than TOS: require the entire price lookback to be present.
    ready = s[COLS[:4]].notna().all(axis=1) & b[COLS[:4]].notna().all(axis=1)
    ready = ready.rolling(n + 1, min_periods=n + 1).sum().eq(n + 1)
    out["rrs"] = (
        positive_ratio(s.close.diff(n), sa) - positive_ratio(b.close.diff(n), ba)
    ).where(ready)
    out["rrs_corr"] = s.close.rolling(n).corr(b.close)
    sv = s.volume.rolling(p["smoothVol"]).mean() if p["smoothVol"] > 1 else s.volume
    bv = v.volume.rolling(p["smoothVol"]).mean() if p["smoothVol"] > 1 else v.volume
    source = (s.volume > 0) & (v.volume > 0) & (sv > 0) & (bv > 0)
    sx = (np.log(sv.where(sv > 0)) if p["useLog"] else sv).where(source)
    bx = (np.log(bv.where(bv > 0)) if p["useLog"] else bv).where(source)
    out["rrv"] = positive_ratio(sx.diff(n), wa(sx.diff().abs(), n)) - positive_ratio(
        bx.diff(n), wa(bx.diff().abs(), n)
    )
    out["rrv_corr"] = sx.rolling(n).corr(bx)
    sa = wa(tr(s).shift(), p["atrPeriod"])
    ba = wa(tr(b).shift(), p["atrPeriod"])
    if p["smoothATR"] > 1:
        sa = sa.rolling(p["smoothATR"]).mean()
        ba = ba.rolling(p["smoothATR"]).mean()
    out["rel_volatility"] = positive_ratio(
        sa.diff(n), wa(sa.diff().abs(), n)
    ) - positive_ratio(ba.diff(n), wa(ba.diff().abs(), n))
    out["rel_volatility_corr"] = sa.rolling(n).corr(ba)
    for name in ["rrs", "rrv", "rel_volatility"]:
        a = out[name]
        bull = flag((a > 0) & (a > a.shift()))
        bear = flag((a < 0) & (a < a.shift()))
        out[name + "_bull_event"] = flag(bull.shift()) & ~flag(bull.shift(2))
        out[name + "_bear_event"] = flag(bear.shift()) & ~flag(bear.shift(2))
    return out.replace([np.inf, -np.inf], np.nan)


def daily_context(daily, index, p):
    daily = daily.sort_index()
    c = daily.close
    f = ema(c, p["dailyFastLength"])
    sl = ema(c, p["dailySlowLength"])
    daily_flags = pd.DataFrame(
        {
            "daily_bull": (c > f) & (f > f.shift()) & (f > sl),
            "daily_bear": (c < f) & (f < f.shift()) & (f < sl),
            "daily_ready": c.notna() & f.shift().notna() & sl.notna(),
        },
        index=daily.index,
    )
    # Warm up slow daily EMA before reporting context. Strictly previous trading date.
    daily_flags["daily_ready"] &= (
        c.notna().rolling(p["dailySlowLength"] + 1).sum().eq(p["dailySlowLength"] + 1)
    )
    daily_flags.index = pd.DatetimeIndex(daily.index.date).tz_localize(TZ)
    left = pd.DataFrame({"session": index.normalize(), "row": np.arange(len(index))})
    right = daily_flags.reset_index(names="session")
    result = pd.merge_asof(
        left.sort_values("session"),
        right.sort_values("session"),
        on="session",
        allow_exact_matches=False,
        direction="backward",
    ).sort_values("row")
    result.index = index
    return (
        result[["daily_bull", "daily_bear", "daily_ready"]].fillna(False).astype(bool)
    )


def market_state(b, daily, p=PARAMS):
    validate_params(p)
    idx = b.index
    c = b.close
    w = p["pivotWidth"]
    f = ema(c, p["m5FastLength"])
    sl = ema(c, p["m5SlowLength"])
    atr = wa(tr(b), p["atrLength"])
    dc = daily_context(daily, idx, p)
    levels = np.full((len(b), 4), np.nan)
    lh = ph = ll = pl = np.nan
    high = b.high.to_numpy()
    low = b.low.to_numpy()
    for i in range(len(b)):
        if not np.isfinite(high[i]) or not np.isfinite(low[i]):
            lh = ph = ll = pl = np.nan
        j = i - w - 1
        if j - w >= 0:
            leftH = high[j - w : j]
            rightH = high[j + 1 : i]
            leftL = low[j - w : j]
            rightL = low[j + 1 : i]
            if (
                np.isfinite(high[j - w : i]).all()
                and high[j] > rightH.max()
                and high[j] >= leftH.max()
            ):
                ph, lh = lh, high[j]
            if (
                np.isfinite(low[j - w : i]).all()
                and low[j] < rightL.min()
                and low[j] <= leftL.min()
            ):
                pl, ll = ll, low[j]
        levels[i] = [lh, ph, ll, pl]
    z = pd.DataFrame(
        levels,
        index=idx,
        columns=["swing_high", "previous_high", "swing_low", "previous_low"],
    )
    structure = z.notna().all(axis=1)
    path = c.diff().abs().rolling(p["efficiencyLength"]).sum()
    efficiency = positive_ratio(c.diff(p["efficiencyLength"]).abs(), path).shift()
    bull = (
        structure
        & (z.swing_high > z.previous_high)
        & (z.swing_low > z.previous_low)
        & (c.shift() > f.shift())
        & (f.shift() > sl.shift())
        & (f.shift() > f.shift(2))
        & (efficiency >= p["trendEfficiencyMin"])
    )
    bear = (
        structure
        & (z.swing_high < z.previous_high)
        & (z.swing_low < z.previous_low)
        & (c.shift() < f.shift())
        & (f.shift() < sl.shift())
        & (f.shift() < f.shift(2))
        & (efficiency >= p["trendEfficiencyMin"])
    )
    shock = (c.diff().abs() > p["shockATRMultiplier"] * atr.shift()) & (atr.shift() > 0)
    recent_shock = shock.astype(float).rolling(p["shockLookback"]).sum().shift() > 0
    recent_range = (
        b.high.shift().rolling(p["compressionLength"]).max()
        - b.low.shift().rolling(p["compressionLength"]).min()
    )
    compression = (
        (atr.shift() > 0)
        & (efficiency < p["rangeEfficiencyMax"])
        & (positive_ratio(recent_range, atr.shift()) < p["compressionATRMultiplier"])
    )
    same_day = pd.Series(idx.date, index=idx).eq(pd.Series(idx.date, index=idx).shift())
    mins = pd.Series(idx.hour * 60 + idx.minute, index=idx)
    prev_mins = mins.shift()
    during = (mins >= 555) & (mins < 930)
    blackout = same_day & (prev_mins >= 555 + p["blackout_minutes"]) & (prev_mins < 930)
    ready = (
        dc.daily_ready
        & structure
        & efficiency.notna()
        & atr.shift().notna()
        & f.shift(2).notna()
        & sl.shift().notna()
        & b[COLS[:4]].notna().all(axis=1)
        & same_day
        & during
    )
    regime = pd.Series(
        np.select(
            [
                ~ready,
                recent_shock,
                dc.daily_bull & bull,
                dc.daily_bear & bear,
                efficiency < p["rangeEfficiencyMax"],
            ],
            [0, 4, 1, -1, 2],
            default=3,
        ),
        index=idx,
    )
    bias = regime.map({1: 1, -1: -1}).fillna(0).astype(int)
    phase = pd.Series(
        np.select(
            [
                ~ready | regime.eq(4),
                compression,
                regime.eq(1) & (c.shift() > c.shift(2)),
                regime.eq(1),
                regime.eq(-1) & (c.shift() < c.shift(2)),
                regime.eq(-1),
            ],
            [0, 5, 1, 2, 3, 4],
            default=0,
        ),
        index=idx,
    )
    bw = ready & blackout & regime.ne(4) & bias.eq(1)
    sw = ready & blackout & regime.ne(4) & bias.eq(-1)
    cb = bw & consecutive(bw, p["confirmationBars"])
    cs = sw & consecutive(sw, p["confirmationBars"])
    z["regime"] = regime
    z["bias"] = bias
    z["phase"] = phase
    z["efficiency"] = efficiency.where(ready)
    z["ready"] = ready
    z["daily_bull"] = dc.daily_bull
    z["daily_bear"] = dc.daily_bear
    z["m5_bull"] = bull
    z["m5_bear"] = bear
    z["confirmed_bull"] = cb
    z["confirmed_bear"] = cs
    z["bull_count"] = bw.rolling(p["confirmationBars"]).sum()
    z["bear_count"] = sw.rolling(p["confirmationBars"]).sum()
    z["new_bull"] = transition(cb)
    z["new_bear"] = transition(cs)
    z["new_dislocation"] = ready & regime.eq(4) & ~regime.shift().eq(4)
    z["entry_status"] = np.select(
        [~ready, ~blackout, regime.eq(4), cb, cs, bw, sw],
        [
            "BLOCKED / DATA WARMUP",
            "OPENING BLACKOUT",
            "DISLOCATION BLOCK",
            "BULL MARKET CONFIRMED",
            "BEAR MARKET CONFIRMED",
            "BULL CONFIRMING",
            "BEAR CONFIRMING",
        ],
        default="NEUTRAL: STRICT SETUPS ONLY",
    )
    z.loc[~ready, ["swing_high", "swing_low"]] = np.nan
    return z


def sector_strength(sector, b, p=PARAMS, self_test=False):
    raw = oscillators(sector, b, b, p).rrs
    f = ema(raw, p["sectorFastLength"])
    sl = ema(raw, p["sectorSlowLength"])
    valid = raw.shift().notna() & f.shift().notna() & sl.shift().notna()
    bull = valid & (f.shift() > 0) & (f.shift() > sl.shift())
    bear = valid & (f.shift() < 0) & (f.shift() < sl.shift())
    strong = (
        bull
        & consecutive(bull, p["confirmationBars"])
        & ~pd.Series(self_test, index=b.index)
    )
    weak = (
        bear
        & consecutive(bear, p["confirmationBars"])
        & ~pd.Series(self_test, index=b.index)
    )
    idx = b.index
    mins = pd.Series(idx.hour * 60 + idx.minute, index=idx).shift()
    same = pd.Series(idx.date, index=idx).eq(pd.Series(idx.date, index=idx).shift())
    eligible = (
        same & (mins >= 555 + p["blackout_minutes"]) & (mins < 930) & (not self_test)
    )
    return pd.DataFrame(
        {
            "sector_rrs": raw,
            "sector_fast": f,
            "sector_slow": sl,
            "sector_confirmed_rrs": raw.shift(),
            "sector_state": pd.Series(
                np.select([strong, weak], [1, -1], default=0), index=idx
            ).where(valid),
            "sector_bull_count": bull.rolling(p["confirmationBars"]).sum(),
            "sector_bear_count": bear.rolling(p["confirmationBars"]).sum(),
            "sector_new_strong": transition(strong) & eligible,
            "sector_new_weak": transition(weak) & eligible,
        },
        index=idx,
    )


def candle_timestamp(value):
    """Interpret broker epochs and naive IST timestamps consistently."""
    if isinstance(value, (int, float)):
        return pd.to_datetime(
            value, unit="ms" if value > 1e11 else "s", utc=True
        ).tz_convert(TZ)
    stamp = pd.Timestamp(value)
    return stamp.tz_localize(TZ) if stamp.tzinfo is None else stamp.tz_convert(TZ)


def parse_candles(
    response,
    interval=5,
    now=None,
    invalid_policy="quarantine",
    instrument="unknown",
    session_profile="nse_cash",
    allow_unusable=False,
):
    """Filter session/completion first; quarantine prices, isolate unavailable volume.

    Providers may retain unusable/empty frames for bounded recovery. Structural
    errors and conflicting duplicates still fail; callers default to strict mode.
    """
    import warnings

    if invalid_policy not in {"quarantine", "raise"}:
        raise ValueError("Unknown invalid_policy")
    if not isinstance(response, dict):
        raise ValueError("Unexpected candle response type")
    payload = response.get("payload", response)
    if not isinstance(payload, dict) or "candles" not in payload:
        raise ValueError(
            "No candles in response; inspect subscription/instrument/date range"
        )
    rows = payload["candles"]
    if not rows and not allow_unusable:
        raise ValueError("Empty candle history; no demo fallback is used")
    parsed = []
    for row in rows:
        if len(row) < 5:
            raise ValueError("Malformed candle")
        stamp = candle_timestamp(row[0])
        if pd.isna(stamp):
            raise ValueError("Missing candle timestamp")
        parsed.append([stamp, *row[1:5], row[5] if len(row) > 5 else np.nan])
    d = pd.DataFrame(parsed, columns=["time", *COLS]).set_index("time").sort_index()
    if not parsed:
        d.index = pd.DatetimeIndex([], tz=TZ, name="time")
        d = d.astype(float)
    d[COLS] = d[COLS].apply(pd.to_numeric, errors="coerce")
    now = pd.Timestamp.now(tz=TZ) if now is None else pd.Timestamp(now)
    now = now.tz_localize(TZ) if now.tzinfo is None else now.tz_convert(TZ)
    received = len(d)
    excluded_noncontinuous = 0
    if interval == 5:
        regular = continuous_mask(d.index, session_profile)
        excluded_noncontinuous = int((~regular).sum())
        d = d[regular]
        if ((d.index.minute % 5 != 0) | (d.index.second != 0)).any():
            raise ValueError("Candle timestamps are not on the 5-minute grid")
        d = d[d.index + pd.Timedelta(minutes=5) <= now]
    else:
        d = d[d.index.normalize() < now.normalize()]
    excluded = received - len(d)
    if d.empty and not allow_unusable:
        raise ValueError("No completed regular-session candles")
    # Compare original values before sanitization: conflicting duplicates must still fail.
    for _, group in d[d.index.duplicated(keep=False)].groupby(level=0):
        if any(group[c].nunique(dropna=False) > 1 for c in COLS):
            raise ValueError("Conflicting duplicate candle")
    duplicates = int(d.index.duplicated().sum())
    d = d[~d.index.duplicated()].copy()
    price = d[COLS[:4]]
    reasons = pd.DataFrame(
        {
            "missing_or_nonfinite_price": ~np.isfinite(price).all(axis=1),
            "zero_or_negative_price": (price <= 0).any(axis=1),
            "high_below_ohlc": d.high < d[["open", "close", "low"]].max(axis=1),
            "low_above_ohlc": d.low > d[["open", "close", "high"]].min(axis=1),
        },
        index=d.index,
    )
    bad_price = reasons.any(axis=1)
    bad_volume = ~np.isfinite(d.volume) | (d.volume < 0)
    samples = []
    for stamp in d.index[bad_price][:5]:
        samples.append(
            {
                "time": stamp.isoformat(),
                "ohlcv": {
                    c: (
                        float(d.loc[stamp, c]) if np.isfinite(d.loc[stamp, c]) else None
                    )
                    for c in COLS
                },
                "reasons": [c for c in reasons if reasons.loc[stamp, c]],
            }
        )
    quality = {
        "instrument": instrument,
        "session_profile": session_profile,
        "session_policy_version": "nse-continuous-v1",
        "excluded_noncontinuous_rows": excluded_noncontinuous,
        "received_rows": received,
        "excluded_session_or_incomplete": excluded,
        "duplicate_rows": duplicates,
        "quarantined_price_rows": int(bad_price.sum()),
        "unavailable_volume_rows": int(bad_volume.sum()),
        "price_reasons": {c: int(reasons[c].sum()) for c in reasons},
        "sample_invalid_rows": samples,
    }
    if invalid_policy == "raise" and (bad_price.any() or (d.volume < 0).any()):
        raise ValueError(
            f"{instrument}: invalid OHLCV; diagnostics=" + json.dumps(quality)
        )
    # Missing/sentinel volume must not discard otherwise usable index prices.
    d.loc[bad_volume, "volume"] = np.nan
    # Keep timestamps, but remove every value on an unusable-price row. Indicators rewarm.
    d.loc[bad_price, COLS] = np.nan
    if bad_price.any() or (
        quality["unavailable_volume_rows"] and instrument != "unknown"
    ):
        warnings.warn(
            f"{instrument}: quarantined {quality['quarantined_price_rows']} price rows; "
            f"{quality['unavailable_volume_rows']} unavailable volume rows. "
            f"Price reasons: {quality['price_reasons']}. See parser diagnostics in quality report.",
            RuntimeWarning,
            stacklevel=2,
        )
    if not d.close.notna().any() and not allow_unusable:
        raise ValueError(
            f"{instrument}: no usable completed prices; diagnostics="
            + json.dumps(quality)
        )
    d.attrs["parser_diagnostics"] = quality
    return d


def aligned_grid(frames, asof=None, session_profile="nse_cash", start=None, end=None):
    nonempty = {name: d for name, d in frames.items() if not d.empty}
    if not nonempty:
        raise ValueError("No source sessions to align")
    dates = sorted(set(day for d in nonempty.values() for day in d.index.normalize()))
    asof = pd.Timestamp.now(tz=TZ) if asof is None else pd.Timestamp(asof)
    first = (
        pd.Timestamp(start)
        if start is not None
        else min(d.index.min() for d in nonempty.values())
    )
    limit = (
        min(pd.Timestamp(end), asof)
        if end is not None
        else min(
            max(d.index.max() for d in nonempty.values()) + pd.Timedelta(minutes=5),
            asof,
        )
    )
    grid = continuous_grid(dates, session_profile, start=first, asof=limit)
    aligned = {name: d.reindex(grid) for name, d in frames.items()}
    report = {
        name: {
            "bars": len(d),
            "missing_ohlc": int(d[COLS[:4]].isna().any(axis=1).sum()),
            "missing_or_zero_volume": int((d.volume.isna() | (d.volume <= 0)).sum()),
            "session_profile": session_profile,
            "parser_diagnostics": d.attrs.get("parser_diagnostics", {}),
            "gap_recovery": d.attrs.get("gap_recovery", {}),
        }
        for name, d in aligned.items()
    }
    return aligned, report
