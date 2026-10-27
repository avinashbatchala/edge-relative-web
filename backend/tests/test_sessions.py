import pandas as pd
import pytest
from app.sessions import continuous_grid, expected_slot
from app.indicators import TZ, parse_candles


@pytest.mark.parametrize("date,offset", [("2026-07-31", "-0400"), ("2026-12-01", "-0500")])
def test_regular_session_and_dst(date, offset):
    grid = continuous_grid([pd.Timestamp(date, tz=TZ)])
    assert len(grid) == 78
    assert grid[0].strftime("%H:%M%z") == "09:30" + offset
    assert grid[-1].strftime("%H:%M") == "15:55"


def test_completion_grace_and_weekends():
    assert expected_slot(pd.Timestamp("2026-10-12 09:35:10", tz=TZ)) is None
    assert expected_slot(pd.Timestamp("2026-10-12 09:35:21", tz=TZ)).strftime("%H:%M") == "09:30"
    assert expected_slot(pd.Timestamp("2026-10-12 16:01", tz=TZ)).strftime("%H:%M") == "15:55"
    assert continuous_grid([pd.Timestamp("2026-10-11", tz=TZ)]).empty


def test_extended_hours_excluded_before_validation():
    rows = [["2026-10-12T09:20:00", 0, 0, 0, 0, -1],
            ["2026-10-12T09:30:00", 100, 101, 99, 100, 10],
            ["2026-10-12T16:00:00", 0, 0, 0, 0, -1]]
    data = parse_candles({"candles": rows}, now=pd.Timestamp("2026-10-12 17:00", tz=TZ))
    assert len(data) == 1 and data.close.iloc[0] == 100
    assert data.attrs["parser_diagnostics"]["excluded_noncontinuous_rows"] == 2
