import asyncio
import csv
import io
from datetime import datetime, timezone
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.responses import JSONResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from .contracts import Instrument, ScanRequest, ScanSnapshot, ChartResponse, Status
from .provider import ProviderError
from .service import Workspace

ROOT = Path(__file__).resolve().parents[2]


def create_app(config_dir=None):
    workspace = Workspace(config_dir or ROOT / "config", ROOT / "data" / "candles")

    @asynccontextmanager
    async def lifespan(app):
        workspace.loop = asyncio.get_running_loop()
        task = asyncio.create_task(workspace.reconcile())
        yield
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        if workspace.feed:
            await asyncio.to_thread(workspace.feed.stop)

    app = FastAPI(
        title="Edge Relative Groww workspace", version="1.0.0", lifespan=lifespan
    )
    app.state.workspace = workspace

    @app.exception_handler(ProviderError)
    async def provider_error(_, exc):
        return JSONResponse(
            status_code=(
                503
                if exc.code
                not in {"future_range", "universe_limit", "benchmark_invalid"}
                else 422
            ),
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @app.get("/api/v1/health", response_model=Status)
    def health():
        return workspace.status()

    @app.get("/api/v1/instruments", response_model=list[Instrument])
    def instruments():
        return workspace.instruments

    @app.post("/api/v1/instruments/sync", response_model=list[Instrument])
    def sync():
        return workspace.sync()

    @app.post("/api/v1/scan", response_model=ScanSnapshot)
    async def scan(request: ScanRequest):
        snapshot = await asyncio.to_thread(workspace.scan, request)
        await workspace.publish("snapshot", snapshot.model_dump(mode="json"))
        return snapshot

    @app.get("/api/v1/snapshot", response_model=ScanSnapshot)
    def snapshot():
        if workspace.snapshot is None:
            raise HTTPException(404, "Fetch Groww history first.")
        return workspace.snapshot

    @app.get("/api/v1/charts/{symbol}", response_model=ChartResponse)
    def chart(symbol: str):
        if symbol not in workspace.charts:
            raise HTTPException(404, "No chart for this symbol; fetch history first.")
        return workspace.charts[symbol]

    @app.get("/api/v1/exports/{symbol}.csv")
    def export(symbol: str):
        data = chart(symbol)
        output = io.StringIO()
        writer = csv.writer(output)
        features = sorted({k for p in data.points for k in p.features})
        writer.writerow(
            ["epoch_seconds", "open", "high", "low", "close", "volume", *features]
        )
        for p in data.points:
            writer.writerow(
                [
                    p.time,
                    p.open,
                    p.high,
                    p.low,
                    p.close,
                    p.volume,
                    *[p.features.get(k) for k in features],
                ]
            )
        safe_name = "".join(c for c in symbol if c.isalnum() or c in "-_")
        return Response(
            output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.csv"'},
        )

    @app.websocket("/api/v1/ws")
    async def ws(socket: WebSocket):
        origin = socket.headers.get("origin")
        host = socket.headers.get("host")
        if origin and origin.split("://", 1)[-1] != host:
            await socket.close(code=1008)
            return
        await socket.accept()
        queue = asyncio.Queue(maxsize=128)
        workspace.clients.add(queue)
        try:
            # Initial status is client-local and does not consume global sequence.
            await socket.send_json(
                {
                    "schema_version": "1.0",
                    "sequence": workspace.sequence,
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                    "type": "status",
                    "payload": workspace.status().model_dump(),
                }
            )
            if workspace.snapshot:
                await socket.send_json(
                    {
                        "schema_version": "1.0",
                        "sequence": workspace.sequence,
                        "sent_at": workspace.snapshot.generated_at.isoformat(),
                        "type": "snapshot",
                        "payload": workspace.snapshot.model_dump(mode="json"),
                    }
                )
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=30)
                except asyncio.TimeoutError:
                    # Status heartbeat is broadcast so sequence remains globally monotonic.
                    await workspace.publish("status", workspace.status().model_dump())
                    continue
                if message is None:
                    await socket.close(code=1013)
                    return
                await socket.send_json(message)
        except Exception:
            pass
        finally:
            workspace.clients.discard(queue)

    dist = ROOT / "frontend" / "dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/")
        def index():
            return FileResponse(dist / "index.html")

    return app


app = create_app()
