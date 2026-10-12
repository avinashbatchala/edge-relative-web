import asyncio
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
from .contracts import (
    Instrument,
    ScanSnapshot,
    ChartResponse,
    ChartPoint,
    ScannerRow,
    Status,
)
from .indicators import (
    PARAMS,
    TZ,
    COLS,
    aligned_grid,
    oscillators,
    market_state,
    sector_strength,
    validate_params,
    ema,
)
from .provider import GrowwProvider, ProviderError
from .scanner import make_row, number
from .feed import FeedWorker

DEFAULT_CONFIG = {
    "price_benchmark": "NIFTY 50",
    "volume_benchmark": "NIFTYBEES",
    "live_enabled": True,
    "publication_grace_seconds": 20,
    "max_stocks": 20,
    "parameters": {},
}
REGIMES = {
    "0": "Unavailable",
    "1": "Bull trend",
    "-1": "Bear trend",
    "2": "Range",
    "3": "Transition",
    "4": "Dislocation",
}


class Workspace:
    def __init__(self, config_dir, cache_dir):
        self.config_dir = Path(config_dir)
        self.config = DEFAULT_CONFIG.copy()
        file = self.config_dir / "scanner.json"
        if file.exists():
            self.config.update(json.loads(file.read_text()))
        self.parameters = {**PARAMS, **self.config["parameters"]}
        validate_params(self.parameters)
        file = self.config_dir / "instruments.json"
        self.instruments = (
            [Instrument.model_validate(i) for i in json.loads(file.read_text())]
            if file.exists()
            else []
        )
        names = [i.symbol for i in self.instruments]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate catalog symbols")
        self.provider = GrowwProvider(Path(cache_dir))
        self.lock = threading.Lock()
        self.snapshot = None
        self.charts = {}
        self.request = None
        self.feed = None
        self.feed_state = "disabled"
        self.message = "Add backend credentials, then fetch Groww history."
        self.sequence = 0
        self.clients = set()
        self.loop = None
        self.reconcile_due = False

    def status(self):
        state = self.feed_state
        if (
            self.feed
            and state == "connected"
            and time.monotonic() - self.feed.last_seen > 60
        ):
            state = "stale"
        return Status(
            configured=self.provider.configured(),
            snapshot_available=self.snapshot is not None,
            feed=state,
            message=self.message,
        )

    async def publish(self, type, payload):
        self.sequence += 1
        message = {
            "schema_version": "1.0",
            "sequence": self.sequence,
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "type": type,
            "payload": payload,
        }
        for queue in list(self.clients):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                self.clients.discard(queue)
                # Clear buffered messages and force reader to close; reconnect reloads snapshot.
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(None)
        return message

    def on_feed(self, type, payload):
        if not self.loop or self.loop.is_closed():
            return

        async def deliver():
            if type == "feed_status":
                self.feed_state = payload["state"]
                self.message = (
                    f"Groww feed {self.feed_state}. Scanner uses completed candles."
                )
                if self.feed_state == "connected":
                    self.reconcile_due = True
                await self.publish("status", self.status().model_dump())
            else:
                await self.publish(type, payload)

        asyncio.run_coroutine_threadsafe(deliver(), self.loop)

    def sync(self):
        with self.lock:
            return self._sync()

    def _sync(self):
        enabled = [i for i in self.instruments if i.enabled]
        if not enabled:
            raise ProviderError(
                "catalog_empty", "Configure instruments.json before fetching."
            )
        resolved = self.provider.resolve(enabled)
        if self.feed:
            self.feed.stop()
            self.feed = None
        lookup = {i.symbol: i for i in resolved}
        self.instruments = [lookup.get(i.symbol, i) for i in self.instruments]
        self.config_dir.mkdir(parents=True, exist_ok=True)
        path = self.config_dir / "instruments.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps([i.model_dump() for i in self.instruments], indent=2)
        )
        temporary.replace(path)
        return self.instruments

    def scan(self, request):
        with self.lock:
            self.provider.connect()
            now = pd.Timestamp.now(tz=TZ)
            if pd.Timestamp(request.end) > now + pd.Timedelta(seconds=30):
                raise ProviderError(
                    "future_range", "Scan end must not be in the future."
                )
            if any(
                not i.groww_symbol or not i.exchange_token
                for i in self.instruments
                if i.enabled
            ):
                self._sync()
            catalog = {i.symbol: i for i in self.instruments if i.enabled}
            stocks = [i for i in catalog.values() if i.kind == "stock"]
            if not stocks:
                raise ProviderError(
                    "catalog_empty", "Enable at least one stock in instruments.json."
                )
            if len(stocks) > self.config["max_stocks"]:
                raise ProviderError(
                    "universe_limit", "This POC supports at most 20 enabled stocks."
                )
            price = request.price_benchmark or self.config["price_benchmark"]
            volume = request.volume_benchmark or self.config["volume_benchmark"]
            parameters = {
                **self.parameters,
                **(request.parameters.model_dump() if request.parameters else {}),
            }
            if price not in catalog or volume not in catalog:
                raise ProviderError(
                    "benchmark_missing",
                    "Enable the configured price and volume benchmarks.",
                )
            if catalog[price].kind != "index" or catalog[volume].kind == "index":
                raise ProviderError(
                    "benchmark_invalid",
                    "Price benchmark must be an index; volume benchmark must be traded.",
                )
            names = {
                price,
                volume,
                *[i.symbol for i in stocks],
                *[i.sector for i in stocks if i.sector and i.sector in catalog],
            }
            fetched = {}
            failures = {}
            for name in sorted(names):
                try:
                    fetched[name] = self.provider.fetch(
                        catalog[name],
                        request.start,
                        request.end,
                        refresh=request.refresh,
                    )
                except ProviderError as exc:
                    if name == price:
                        raise
                    failures[name] = exc.message
            if price not in fetched:
                raise ProviderError(
                    "benchmark_missing", "Price benchmark has no usable history."
                )
            aligned, diagnostics = aligned_grid(
                fetched, asof=min(pd.Timestamp(request.end), now)
            )
            benchmark = aligned[price]
            proxy = aligned.get(volume, benchmark.copy() * np.nan)
            try:
                daily = self.provider.fetch(
                    catalog[price],
                    pd.Timestamp(request.start) - pd.Timedelta(days=150),
                    request.end,
                    interval=1440,
                    refresh=request.refresh,
                )
                market = market_state(benchmark, daily, parameters)
            except ProviderError as exc:
                failures["daily_context"] = exc.message
                market = pd.DataFrame(
                    {
                        "regime": 0,
                        "ready": False,
                        "entry_status": "BLOCKED / DAILY DATA",
                    },
                    index=benchmark.index,
                )
            expected = self.expected_slot(min(pd.Timestamp(request.end), now))
            historical = pd.Timestamp(request.end).tz_convert(
                TZ
            ).date() < now.date() or (
                expected is None and benchmark.index[-1].date() < now.date()
            )
            if (
                request.live
                and pd.Timestamp(request.end).tz_convert(TZ).date() != now.date()
            ):
                raise ProviderError(
                    "live_range", "Live mode requires a date range ending today."
                )
            rows = []
            charts = {}
            for instrument in stocks:
                if instrument.symbol not in aligned:
                    rows.append(
                        ScannerRow(
                            symbol=instrument.symbol,
                            quality="error",
                            reasons=[
                                failures.get(instrument.symbol, "No usable prices")
                            ],
                        )
                    )
                    continue
                bars = aligned[instrument.symbol]
                features = oscillators(bars, benchmark, proxy, parameters)
                if instrument.sector in aligned:
                    features = features.join(
                        sector_strength(
                            aligned[instrument.sector], benchmark, parameters
                        )
                    )
                features = features.join(market.add_prefix("market_"))
                features["price_ema8"] = ema(bars.close, 8)
                features["price_ema21"] = ema(bars.close, 21)
                stale = (
                    not historical
                    and expected is not None
                    and (
                        bars.index[-1] < expected
                        or number(bars.close.get(expected)) is None
                        or number(benchmark.close.get(expected)) is None
                    )
                )
                row = make_row(
                    instrument.symbol,
                    bars,
                    features,
                    market,
                    request,
                    stale,
                    historical,
                )
                rows.append(row)
                points = []
                for stamp, bar in bars.iterrows():

                    def native(value):
                        if isinstance(value, str):
                            return value
                        if isinstance(value, (bool, np.bool_)):
                            return bool(value)
                        return number(value)

                    points.append(
                        ChartPoint(
                            time=int(stamp.timestamp()),
                            **{c: number(bar[c]) for c in COLS},
                            features={
                                k: native(v) for k, v in features.loc[stamp].items()
                            },
                        )
                    )
                charts[instrument.symbol] = ChartResponse(
                    symbol=instrument.symbol,
                    price_benchmark=price,
                    volume_benchmark=volume,
                    sector_benchmark=instrument.sector,
                    parameters=parameters,
                    regime_labels=REGIMES,
                    quality=row,
                    points=points,
                )
            diagnostics["fetch_failures"] = failures
            snapshot = ScanSnapshot(
                generated_at=datetime.now(timezone.utc),
                as_of=benchmark.index[-1].to_pydatetime(),
                price_benchmark=price,
                volume_benchmark=volume,
                rows=rows,
                diagnostics=diagnostics,
            )
            # Publish the whole run atomically after all calculations succeed.
            self.charts = charts
            self.snapshot = snapshot
            self.request = request
            self.message = "Groww history loaded. Scanner values are completed-candle observations."
            if not request.live and self.feed:
                self.feed.stop()
                self.feed = None
                self.feed_state = "disabled"
            if self.config["live_enabled"] and self.feed is None and request.live:
                self.feed = FeedWorker(
                    self.provider, [catalog[n] for n in sorted(names)], self.on_feed
                )
                self.feed.start()
            return snapshot

    def expected_slot(self, asof):
        local = pd.Timestamp(asof).tz_convert(TZ) - pd.Timedelta(
            seconds=self.config["publication_grace_seconds"]
        )
        if local.weekday() > 4:
            return None
        first = local.normalize() + pd.Timedelta(hours=9, minutes=15)
        if local < first + pd.Timedelta(minutes=5):
            return None
        last = local.normalize() + pd.Timedelta(hours=15, minutes=25)
        return min(local.floor("5min") - pd.Timedelta(minutes=5), last)

    async def reconcile(self):
        previous_slot = None
        while True:
            await asyncio.sleep(10)
            request = self.request
            if not request or not request.live:
                continue
            now = pd.Timestamp.now(tz=TZ)
            minutes = now.hour * 60 + now.minute
            slot = self.expected_slot(now)
            if not (now.weekday() < 5 and 560 <= minutes <= 935):
                continue
            if not self.reconcile_due and slot == previous_slot:
                continue
            self.reconcile_due = False
            rolling_start = now - (
                pd.Timestamp(request.end) - pd.Timestamp(request.start)
            )
            live_request = request.model_copy(
                update={
                    "start": rolling_start.to_pydatetime(),
                    "end": now.to_pydatetime(),
                    "refresh": False,
                }
            )
            try:
                snapshot = await asyncio.to_thread(self.scan, live_request)
                previous_slot = slot
                await self.publish("snapshot", snapshot.model_dump(mode="json"))
            except ProviderError as exc:
                self.message = exc.message
                await self.mark_stale()
                await self.publish("status", self.status().model_dump())
            except Exception:
                self.message = "History reconciliation failed; last snapshot is stale."
                await self.mark_stale()
                await self.publish("status", self.status().model_dump())

    async def mark_stale(self):
        if self.snapshot is None:
            return
        rows = [
            row.model_copy(
                update={
                    "quality": "stale",
                    "direction": "unavailable",
                    "reasons": [
                        "History reconciliation failed; confirmed data is stale"
                    ],
                }
            )
            for row in self.snapshot.rows
        ]
        self.snapshot = self.snapshot.model_copy(update={"rows": rows})
        lookup = {row.symbol: row for row in rows}
        self.charts = {
            symbol: chart.model_copy(update={"quality": lookup[symbol]})
            for symbol, chart in self.charts.items()
        }
        await self.publish("snapshot", self.snapshot.model_dump(mode="json"))
