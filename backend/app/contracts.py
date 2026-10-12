"""Versioned wire models. Export OpenAPI and WebSocket schemas from these models."""

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Instrument(Contract):
    symbol: str = Field(pattern=r"^[A-Z0-9 &.\-]{1,40}$")
    kind: Literal["stock", "index", "etf"]
    enabled: bool = True
    sector: str | None = None
    groww_symbol: str | None = None
    exchange_token: str | None = None
    exchange: Literal["NSE"] = "NSE"
    segment: Literal["CASH"] = "CASH"


class IndicatorSettings(Contract):
    length: int = Field(default=12, ge=2, le=200)
    smoothVol: int = Field(default=3, ge=1, le=50)
    atrPeriod: int = Field(default=14, ge=2, le=200)


class ScanRequest(Contract):
    start: datetime
    end: datetime
    refresh: bool = False
    live: bool = False
    market_filter: bool = False
    sector_filter: bool = False
    volume_filter: bool = False
    min_volume_momentum: float = Field(default=0, allow_inf_nan=False)
    price_benchmark: str | None = None
    volume_benchmark: str | None = None
    parameters: IndicatorSettings | None = None

    @model_validator(mode="after")
    def check_range(self):
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("Timezone offset required")
        if self.start >= self.end:
            raise ValueError("Start must precede end")
        if (self.end - self.start).days > 90:
            raise ValueError("Maximum range is 90 days")
        return self


class ScannerRow(Contract):
    symbol: str
    candle_time: int | None = None
    close: float | None = None
    rrs: float | None = None
    previous_rrs: float | None = None
    rrv: float | None = None
    relative_volatility: float | None = None
    sector_rrs: float | None = None
    sector_state: int | None = None
    market_regime: int | None = None
    direction: Literal["bullish", "bearish", "mixed", "unavailable"] = "unavailable"
    quality: Literal["ready", "historical", "stale", "missing", "warmup", "error"] = (
        "missing"
    )
    reasons: list[str] = Field(default_factory=list)


class Status(Contract):
    provider: Literal["groww"] = "groww"
    configured: bool
    snapshot_available: bool = False
    feed: Literal["disabled", "connecting", "connected", "stale", "disconnected"] = (
        "disabled"
    )
    message: str


class ScanSnapshot(Contract):
    schema_version: Literal["1.0"] = "1.0"
    generated_at: datetime
    as_of: datetime
    timezone: Literal["Asia/Kolkata"] = "Asia/Kolkata"
    price_benchmark: str
    volume_benchmark: str
    rows: list[ScannerRow]
    diagnostics: dict


class ChartPoint(Contract):
    time: int
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None
    features: dict[str, float | int | bool | str | None]


class ChartResponse(Contract):
    run_id: str | None = None
    schema_version: Literal["1.0"] = "1.0"
    symbol: str
    timezone: Literal["Asia/Kolkata"] = "Asia/Kolkata"
    price_unit: Literal["INR"] = "INR"
    volume_unit: Literal["shares"] = "shares"
    price_benchmark: str
    volume_benchmark: str
    sector_benchmark: str | None
    parameters: dict
    regime_labels: dict[str, str]
    quality: ScannerRow
    points: list[ChartPoint]


class Envelope(Contract):
    schema_version: Literal["1.0"] = "1.0"
    sequence: int
    sent_at: datetime


class StatusEvent(Envelope):
    type: Literal["status"] = "status"
    payload: Status


class Quote(Contract):
    symbol: str
    price: float = Field(gt=0)
    time: int
    provisional: Literal[True] = True


class QuoteEvent(Envelope):
    type: Literal["quote"] = "quote"
    payload: Quote


class SnapshotEvent(Envelope):
    type: Literal["snapshot"] = "snapshot"
    payload: ScanSnapshot
