"""Groww history adapter. Credentials stay in memory; cache contains market data only."""

import hashlib
import json
import os
import time
from pathlib import Path
import pandas as pd
from .contracts import Instrument
from .indicators import TZ, parse_candles


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
        cursor = start
        while cursor < end:
            stop = min(cursor + pd.Timedelta(days=29 if interval == 5 else 179), end)
            key = hashlib.sha256(
                f"{instrument.groww_symbol}|{cursor}|{stop}|{interval}|v2".encode()
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
            rows.extend(payload["candles"])
            cursor = stop
        try:
            data = parse_candles(
                {"candles": rows},
                interval=interval,
                now=min(end, pd.Timestamp.now(tz=TZ)),
                instrument=instrument.symbol,
            )
            data = data.loc[
                data.index >= (start if interval == 5 else start.normalize())
            ]
            if data.empty:
                raise ValueError("No data")
            return data
        except ValueError:
            raise ProviderError(
                "history_invalid",
                f"{instrument.symbol}: no usable history or conflicting/malformed candles. Verify date range and instrument.",
            ) from None
