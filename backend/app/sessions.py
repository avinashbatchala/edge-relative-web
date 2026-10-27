"""US regular sessions in New York time; dates must be observed from market data."""
import pandas as pd

TZ = "America/New_York"
OPEN_MINUTE = 9 * 60 + 30


def profile_name(instrument_or_profile="us_regular"):
    profile = getattr(instrument_or_profile, "session_profile", instrument_or_profile)
    if profile not in {"us_regular"}:
        raise ValueError("Unknown session profile")
    return profile


def close_minute(day, instrument_or_profile="us_regular"):
    profile_name(instrument_or_profile)
    return 16 * 60


def continuous_mask(index, instrument_or_profile="us_regular"):
    local = index.tz_convert(TZ)
    minutes = local.hour * 60 + local.minute
    ends = [close_minute(day, instrument_or_profile) for day in local]
    return (local.weekday < 5) & (minutes >= OPEN_MINUTE) & (minutes < ends)


def continuous_grid(dates, instrument_or_profile="us_regular", start=None, asof=None):
    grid = pd.DatetimeIndex([], tz=TZ)
    for day in sorted({pd.Timestamp(d).date() for d in dates}):
        if day.weekday() > 4:
            continue
        midnight = pd.Timestamp(day, tz=TZ)
        grid = grid.union(
            pd.date_range(
                midnight + pd.Timedelta(minutes=OPEN_MINUTE),
                midnight
                + pd.Timedelta(minutes=close_minute(day, instrument_or_profile) - 5),
                freq="5min",
            )
        )
    if start is not None:
        grid = grid[grid >= pd.Timestamp(start).tz_convert(TZ)]
    if asof is not None:
        grid = grid[grid + pd.Timedelta(minutes=5) <= pd.Timestamp(asof).tz_convert(TZ)]
    return grid


def expected_slot(asof, instrument_or_profile="us_regular", grace_seconds=20):
    local = pd.Timestamp(asof).tz_convert(TZ) - pd.Timedelta(seconds=grace_seconds)
    if local.weekday() > 4:
        return None
    first = local.normalize() + pd.Timedelta(minutes=OPEN_MINUTE)
    if local < first + pd.Timedelta(minutes=5):
        return None
    last = local.normalize() + pd.Timedelta(
        minutes=close_minute(local, instrument_or_profile) - 5
    )
    return min(local.floor("5min") - pd.Timedelta(minutes=5), last)
