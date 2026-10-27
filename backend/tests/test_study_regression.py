from study_fixture import *


def run_checks():
    checks = []

    def check(name, condition):
        assert condition, name
        checks.append(name)

    x = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    check(
        "Wilder uses SMA seed then alpha=1/n",
        np.allclose(wa(x, 3).dropna(), [2, 8 / 3, 31 / 9]),
    )
    idx = pd.date_range("2026-08-03 09:30", periods=4, freq="5min", tz=TZ)
    fixture = pd.DataFrame(
        {
            "open": [10, 12, 9, 10],
            "high": [11, 13, 11, 12],
            "low": [9, 10, 8, 9],
            "close": [10, 12, 9, 11],
            "volume": [1, 2, 3, 4],
        },
        index=idx,
    )
    check(
        "True range uses preceding close", np.allclose(tr(fixture).iloc[1:], [3, 4, 3])
    )
    check("Lagged TR preserves two-bar-old close", tr(fixture).shift().iloc[2] == 3)
    source = pd.Series([1.0, 2.0, np.nan, 4.0, 5.0, 6.0])
    check(
        "Wilder resets and rewarms after missing data",
        np.allclose(wa(source, 2).iloc[[1, 4, 5]], [1.5, 4.5, 5.25])
        and np.isnan(wa(source, 2).iloc[3]),
    )
    invalid = pd.Series([True, True, False, True, True, True])
    check(
        "Confirmation requires consecutive bars",
        consecutive(invalid, 3).tolist() == [False, False, False, False, False, True],
    )
    s, b, v, sectors, daily = synthetic_data()
    r, b, m, q = run_studies(s, b, v, sectors, daily)
    same = oscillators(s["AAPL"], s["AAPL"], s["AAPL"])
    check(
        "Self-comparison yields zero for all oscillators",
        all(np.allclose(same[c].dropna(), 0) for c in ["rrs", "rrv", "rel_volatility"]),
    )
    no_volume = oscillators(s["AAPL"], b, b)
    check("Price index missing volume does not invent RRV", no_volume.rrv.isna().all())
    flat = s["AAPL"].copy()
    flat[COLS[:4]] = 100
    flat.volume = 100
    z = oscillators(flat, flat, flat)
    check(
        "Zero denominators yield unavailable, never infinity",
        z[["rrs", "rrv", "rel_volatility"]].isna().all().all(),
    )
    gap = s["AAPL"].copy()
    gap.iloc[100] = np.nan
    g = oscillators(gap, b, v)
    check(
        "Missing stock bar invalidates and rewarms RRS",
        g.rrs.iloc[100:113].isna().all(),
    )
    original = oscillators(s["AAPL"], b, v)
    altered = s["AAPL"].copy()
    altered.iloc[600:, 0:4] *= 1.5
    alt = oscillators(altered, b, v)
    check(
        "Oscillators have no future-price leakage",
        original.iloc[:600].equals(alt.iloc[:600]),
    )
    later = b.copy()
    later.iloc[600:, 0:4] *= 1.5
    altered_daily = daily.copy()
    altered_daily.loc[
        altered_daily.index.normalize() >= b.index[600].normalize(), "close"
    ] *= 1.7
    alt_market = market_state(later, altered_daily)
    check(
        "Pivots and daily context have no future-data leakage",
        m.iloc[:600].equals(alt_market.iloc[:600]),
    )
    for day in b.index.normalize().unique():
        daymask = b.index.normalize() == day
        check(
            f"Opening observation is unavailable {day.date()}",
            m.loc[daymask].regime.iloc[0] == 0,
        )
    ctx = daily_context(daily, b.index, PARAMS)
    changed = daily.copy()
    day = b.index[100].normalize()
    changed.loc[day, "close"] *= 9
    check(
        "Current daily candle excluded from same-session context",
        ctx.loc[b.index.normalize() == day].equals(
            daily_context(changed, b.index, PARAMS).loc[b.index.normalize() == day]
        ),
    )
    base = fixture.index[0]
    rows = [[int(t.timestamp()), *row.tolist()] for t, row in fixture.iterrows()]
    parsed = parse_candles({"candles": rows}, now=base + pd.Timedelta(minutes=12))
    check("Forming candle is excluded", len(parsed) == 2)
    iso = [
        [t.strftime("%Y-%m-%dT%H:%M:%S"), *row.tolist(), None]
        for t, row in fixture.iterrows()
    ]
    check(
        "New Schwab ISO payload accepted",
        len(parse_candles({"candles": iso}, now=base + pd.Timedelta(days=1))) == 4,
    )
    check(
        "Identical overlap duplicate deduplicated",
        len(
            parse_candles(
                {"candles": rows + [rows[0]]}, now=base + pd.Timedelta(days=1)
            )
        )
        == 4,
    )
    bad = [r.copy() for r in rows]
    bad[0][2] = 0.1
    try:
        parse_candles(
            {"candles": bad}, now=base + pd.Timedelta(days=1), invalid_policy="raise"
        )
        ok = False
    except ValueError:
        ok = True
    check("Invalid candle OHLC rejected", ok)
    conflicting = rows[0].copy()
    conflicting[-1] = 999
    try:
        parse_candles(
            {"candles": rows + [conflicting]}, now=base + pd.Timedelta(days=1)
        )
        ok = False
    except ValueError:
        ok = True
    check("Conflicting duplicate rejected", ok)
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        quarantined = parse_candles({"candles": bad}, now=base + pd.Timedelta(days=1))
    check(
        "Bad prices quarantined without losing timestamps",
        len(quarantined) == 4
        and quarantined.iloc[0].isna().all()
        and quarantined.close.iloc[1:].notna().all(),
    )
    check(
        "Reason and original sample preserved",
        quarantined.attrs["parser_diagnostics"]["price_reasons"]["high_below_ohlc"] == 1
        and quarantined.attrs["parser_diagnostics"]["sample_invalid_rows"][0]["ohlcv"][
            "high"
        ]
        == 0.1,
    )
    sentinel = [r.copy() for r in rows]
    for row in sentinel:
        row[-1] = -1
    index_prices = parse_candles({"candles": sentinel}, now=base + pd.Timedelta(days=1))
    check(
        "Negative volume sentinel preserves index prices",
        index_prices.close.notna().all() and index_prices.volume.isna().all(),
    )
    outside = [int((base - pd.Timedelta(hours=1)).timestamp()), 0, 0, 0, 0, -1]
    filtered = parse_candles(
        {"candles": [outside, *rows]},
        now=base + pd.Timedelta(days=1),
        invalid_policy="raise",
    )
    check(
        "Out-of-session placeholder excluded before validation",
        len(filtered) == 4
        and filtered.attrs["parser_diagnostics"]["excluded_session_or_incomplete"] == 1,
    )
    all_bad = [[r[0], 0, 0, 0, 0, 0] for r in rows]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        try:
            parse_candles({"candles": all_bad}, now=base + pd.Timedelta(days=1))
            ok = False
        except ValueError as exc:
            ok = "no usable completed prices" in str(exc)
    check("All-invalid price history still stops", ok)
    check(
        "Diagnostics survive alignment",
        bool(
            aligned_grid({"s": quarantined}, asof=base + pd.Timedelta(minutes=20))[1][
                "s"
            ]["parser_diagnostics"]
        ),
    )

    missing = fixture.drop(fixture.index[1])
    aligned, _ = aligned_grid(
        {"s": fixture, "b": missing}, asof=base + pd.Timedelta(minutes=20)
    )
    check(
        "Missing benchmark remains missing on canonical grid",
        np.isnan(aligned["b"].close.iloc[1]),
    )
    sec = sector_strength(b, b, self_test=True)
    check(
        "Sector self-test cannot confirm strength or weakness",
        sec.sector_state.dropna().eq(0).all(),
    )
    check(
        "All features finite or explicitly missing",
        not np.isinf(
            r["AAPL"]["features"].select_dtypes(include="number").to_numpy()
        ).any(),
    )
    print(
        f"{len(checks)} checks passed: smoothing, formulas, missing data, confirmations, parsing, and no look-ahead."
    )
    return checks


if __name__ == "__main__":
    run_checks()


def test_notebook_regressions():
    assert len(run_checks()) >= 34
