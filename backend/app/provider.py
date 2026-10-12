"""Groww history adapter. Credentials stay in memory; cache contains market data only."""

import hashlib
import json
import os
import time
from pathlib import Path
import pandas as pd
from .contracts import Instrument
from .indicators import TZ, parse_candles, candle_timestamp
from .sessions import continuous_grid


class ProviderError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(message)


class GrowwProvider:
    def __init__(self, cache: Path):
        self.cache = cache
        cache.mkdir(parents=True, exist_ok=True)
        self.api = None
        self.feed_client = None

    @staticmethod
    def configured():
        return bool(
            os.getenv("GROWW_ACCESS_TOKEN")
            or (os.getenv("GROWW_API_KEY") and os.getenv("GROWW_API_SECRET"))
        )

    def connect(self):
        if self.api is not None:
            return self.api
        if not self.configured():
            raise ProviderError(
                "credentials_missing",
                "Set GROWW_ACCESS_TOKEN or GROWW_API_KEY and GROWW_API_SECRET on the backend.",
            )
        try:
            from growwapi import GrowwAPI

            token = os.getenv("GROWW_ACCESS_TOKEN") or GrowwAPI.get_access_token(
                api_key=os.environ["GROWW_API_KEY"],
                secret=os.environ["GROWW_API_SECRET"],
            )
            self.api = GrowwAPI(token)
            return self.api
        except ImportError:
            raise ProviderError(
                "sdk_missing", "Install backend requirements, including growwapi."
            ) from None
        except Exception:
            raise ProviderError(
                "authentication_failed",
                "Groww authentication failed. Check key approval, token expiry and subscription.",
            ) from None

    def resolve(self, catalog):
        api = self.connect()
        try:
            master = api.get_all_instruments()
            if not isinstance(master, pd.DataFrame):
                master = pd.DataFrame(master)
            if not {"exchange", "segment", "groww_symbol", "exchange_token"}.issubset(
                master.columns
            ):
                raise ProviderError(
                    "instrument_schema",
                    "Groww instrument master does not contain the required identity fields.",
                )
            master = master[
                master.exchange.astype(str).str.upper().eq("NSE")
                & master.segment.astype(str).str.upper().isin(["CASH", "INDEX"])
            ]
            result = []
            normalize = lambda name: "".join(
                c for c in str(name).upper() if c.isalnum()
            )
            for instrument in catalog:
                candidate = instrument.groww_symbol or instrument.symbol
                target = normalize(candidate)
                matches = pd.Series(False, index=master.index)
                fields = (
                    ["groww_symbol"]
                    if instrument.groww_symbol
                    else ["groww_symbol", "trading_symbol", "name"]
                )
                for field in fields:
                    if field in master:
                        matches |= master[field].map(normalize).eq(target)
                hits = master[matches].drop_duplicates("groww_symbol")
                if len(hits) != 1:
                    raise ProviderError(
                        "instrument_unresolved",
                        f"Configure an exact Groww symbol for {instrument.symbol}; master match is absent or ambiguous.",
                    )
                row = hits.iloc[0]
                result.append(
                    instrument.model_copy(
                        update={
                            "groww_symbol": str(row.groww_symbol),
                            "exchange_token": str(row.exchange_token),
                        }
                    )
                )
            return result
        except ProviderError:
            raise
        except Exception:
            raise ProviderError(
                "instrument_fetch_failed",
                "Groww instrument master fetch failed. Check network and subscription.",
            ) from None

    def fetch(self, instrument: Instrument, start, end, interval=5, refresh=False):
        api = self.connect()
        start = pd.Timestamp(start).tz_convert(TZ)
        end = pd.Timestamp(end).tz_convert(TZ)
        constant = "CANDLE_INTERVAL_MIN_5" if interval == 5 else "CANDLE_INTERVAL_DAY"
        if not hasattr(api, constant):
            raise ProviderError(
                "sdk_version",
                "Groww SDK is missing required candle interval constants.",
            )
        rows = []
        chunks = []
        cursor = start
        while cursor < end:
            stop = min(cursor + pd.Timedelta(days=29 if interval == 5 else 179), end)
            key = hashlib.sha256(
                f"{instrument.groww_symbol}|{cursor}|{stop}|{interval}|{instrument.session_profile}|v3".encode()
            ).hexdigest()
            file = self.cache / f"{key}.json"
            immutable = stop.normalize() < pd.Timestamp.now(tz=TZ).normalize()
            if immutable and file.exists() and not refresh:
                try:
                    response = json.loads(file.read_text())
                except (ValueError, OSError):
                    response = None
            else:
                response = None
            if response is None:
                for attempt in range(3):
                    try:
                        response = api.get_historical_candles(
                            exchange="NSE",
                            segment="CASH",
                            groww_symbol=instrument.groww_symbol,
                            start_time=cursor.strftime("%Y-%m-%d %H:%M:%S"),
                            end_time=stop.strftime("%Y-%m-%d %H:%M:%S"),
                            candle_interval=getattr(api, constant),
                        )
                        break
                    except Exception:
                        if attempt == 2:
                            raise ProviderError(
                                "history_fetch_failed",
                                f"Groww history fetch failed for {instrument.symbol}; check authentication, entitlement and request limits.",
                            ) from None
                        time.sleep(2**attempt)
                time.sleep(0.4)
            payload = (
                response.get("payload", response) if isinstance(response, dict) else {}
            )
            if not isinstance(payload, dict) or "candles" not in payload:
                raise ProviderError(
                    "history_schema",
                    f"Groww returned no candle payload for {instrument.symbol}.",
                )
            if immutable:
                temporary = file.with_suffix(".tmp")
                temporary.write_text(json.dumps(response))
                temporary.replace(file)
            chunks.append((file, cursor, stop, response, immutable))
            # Groww includes the end timestamp and may return a partial boundary
            # candle. Let the next chunk own that candle rather than combining
            # incompatible endpoint observations. In-chunk duplicates still fail.
            rows.extend(
                row for row in payload["candles"]
                if interval != 5 or cursor <= candle_timestamp(row[0]) < stop
            )
            cursor = stop
        if not rows and interval != 5:
            raise ProviderError(
                "history_empty",
                f"{instrument.symbol}: Groww returned no candles for this range.",
            )
        try:
            data = parse_candles(
                {"candles": rows},
                interval=interval,
                now=min(end, pd.Timestamp.now(tz=TZ)),
                instrument=instrument.symbol,
                session_profile=instrument.session_profile,
                allow_unusable=interval == 5,
            )
            data = data.loc[
                data.index >= (start if interval == 5 else start.normalize())
            ]
            if data.empty and interval != 5:
                raise ValueError("No data")
            if interval == 5:
                data.attrs["_cache_chunks"] = [
                    (str(file), left.isoformat(), right.isoformat())
                    for file, left, right, _, immutable in chunks
                    if immutable
                ]
                data = self.repair_gaps(instrument, data, start, end)
            return data
        except ValueError:
            raise ProviderError(
                "history_invalid",
                f"{instrument.symbol}: no usable history or conflicting/malformed candles. Verify date range and instrument.",
            ) from None

    def repair_gaps(self, instrument, data, start, end, session_dates=None):
        """Retry actual completed-session holes; never forward-fill or synthesize OHLCV.

        Dates must be observed locally or by a peer, not inferred from weekdays.
        At most two attempts per contiguous range and eight calls per instrument.
        """
        start, end = pd.Timestamp(start).tz_convert(TZ), pd.Timestamp(end).tz_convert(
            TZ
        )
        cutoff = min(end, pd.Timestamp.now(tz=TZ) - pd.Timedelta(seconds=20))
        dates = session_dates if session_dates is not None else data.index.normalize()
        grid = continuous_grid(dates, instrument, start=start, asof=cutoff)
        attrs = dict(data.attrs)
        result = data.reindex(grid).copy()
        report = dict(attrs.get("gap_recovery", {}))
        report.setdefault("requests", 0)
        report.setdefault("recovered_price_bars", 0)
        report.setdefault("recovered_volume_bars", 0)
        report.setdefault("repaired_timestamps", [])
        report.setdefault("failed_requests", 0)
        prices = ["open", "high", "low", "close"]

        def missing():
            price = result[prices].isna().any(axis=1)
            volume = (
                result.volume.isna() & ~price
                if instrument.kind != "index"
                else price & False
            )
            return price, volume

        price, volume = missing()
        holes = grid[price | volume]
        groups = []
        for stamp in holes:
            if not groups or stamp - groups[-1][-1] != pd.Timedelta(minutes=5):
                groups.append([])
            groups[-1].append(stamp)
        api = None
        for group in groups:
            for attempt in range(2):
                price, volume = missing()
                wanted = pd.DatetimeIndex(
                    [t for t in group if price.loc[t] or volume.loc[t]]
                )
                if wanted.empty or report["requests"] >= 8:
                    break
                if api is None:
                    api = self.connect()
                report["requests"] += 1
                try:
                    response = api.get_historical_candles(
                        exchange="NSE",
                        segment="CASH",
                        groww_symbol=instrument.groww_symbol,
                        start_time=wanted[0].strftime("%Y-%m-%d %H:%M:%S"),
                        end_time=(wanted[-1] + pd.Timedelta(minutes=5)).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                        candle_interval=api.CANDLE_INTERVAL_MIN_5,
                    )
                    payload = (
                        response.get("payload", response)
                        if isinstance(response, dict)
                        else {}
                    )
                    if not payload.get("candles"):
                        continue
                    recovered = parse_candles(
                        response,
                        now=cutoff,
                        instrument=instrument.symbol,
                        session_profile=instrument.session_profile,
                    )
                    for stamp in wanted.intersection(recovered.index):
                        bar = recovered.loc[stamp]
                        if bar[prices].isna().any():
                            continue
                        changed = False
                        if price.loc[stamp]:
                            result.loc[stamp, prices] = bar[prices]
                            if pd.notna(bar.volume):
                                result.loc[stamp, "volume"] = bar.volume
                            report["recovered_price_bars"] += 1
                            changed = True
                        elif (
                            volume.loc[stamp]
                            and pd.notna(bar.volume)
                            and bar[prices].equals(result.loc[stamp, prices])
                        ):
                            result.loc[stamp, "volume"] = bar.volume
                            report["recovered_volume_bars"] += 1
                            changed = True
                        if (
                            changed
                            and stamp.isoformat() not in report["repaired_timestamps"]
                        ):
                            report["repaired_timestamps"].append(stamp.isoformat())
                except Exception:
                    # Broker failures can contain tokens; diagnostics never retain exceptions.
                    report["failed_requests"] += 1
                finally:
                    time.sleep(0.4)
        price, volume = missing()
        report["remaining_price_gaps"] = int(price.sum())
        report["remaining_volume_gaps"] = int(volume.sum())
        report["unresolved_timestamps"] = [t.isoformat() for t in grid[price | volume]]
        report["request_budget"] = 8
        result.attrs = {**attrs, "gap_recovery": report}
        self._persist_repairs(result)
        return result

    def _persist_repairs(self, data):
        # Preserve raw broker rows (including excluded auction rows); replace only
        # timestamps repaired from a validated response, even on the peer-date pass.
        repaired = set(data.attrs["gap_recovery"]["repaired_timestamps"])
        if not repaired:
            return
        for path, left, right in data.attrs.get("_cache_chunks", []):
            file = Path(path)
            selected = data.loc[
                (data.index >= pd.Timestamp(left)) & (data.index < pd.Timestamp(right))
            ]
            updates = {
                stamp.isoformat(): [
                    stamp.isoformat(),
                    *[None if pd.isna(v) else float(v) for v in bar],
                ]
                for stamp, bar in selected.iterrows()
                if stamp.isoformat() in repaired
            }
            if not updates:
                continue
            try:
                response = json.loads(file.read_text())
                payload = response.get("payload", response)
                original = [
                    row
                    for row in payload["candles"]
                    if candle_timestamp(row[0]).isoformat() not in updates
                ]
                payload["candles"] = original + list(updates.values())
                temporary = file.with_suffix(".tmp")
                temporary.write_text(json.dumps(response))
                temporary.replace(file)
            except (ValueError, OSError, KeyError, IndexError, TypeError):
                # A cache write failure must not discard verified in-memory prices.
                data.attrs["gap_recovery"]["cache_write_failed"] = True
