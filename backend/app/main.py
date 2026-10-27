import asyncio
from datetime import datetime, timezone
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.responses import JSONResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from .contracts import Instrument, ScanRequest, ScanSnapshot, ChartResponse, Status
from .provider import ProviderError
from .service import Workspace
from .exports import safe_filename

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
        title="Edge Relative Schwab workspace", version="1.0.0", lifespan=lifespan
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
            raise HTTPException(404, "Fetch Schwab history first.")
        return workspace.snapshot

    @app.get("/api/v1/charts/{symbol}", response_model=ChartResponse)
    def chart(symbol: str):
        if symbol not in workspace.charts:
            raise HTTPException(404, "No chart for this symbol; fetch history first.")
        return workspace.charts[symbol]

    def captured_export(run_id: str | None):
        run = workspace.export_run
        if run is None:
            raise HTTPException(
                404, "Fetch Schwab history first; no loaded export run exists."
            )
        if run_id is not None and run_id != run.run_id:
            raise HTTPException(
                409,
                "The displayed run was replaced. Refresh the chart and retry the export.",
            )
        return run

    @app.get(
        "/api/v1/exports/run.zip",
        response_class=Response,
        responses={
            200: {
                "content": {
                    "application/zip": {
                        "schema": {"type": "string", "format": "binary"}
                    }
                }
            },
            404: {"description": "No loaded run"},
            409: {"description": "Run replaced"},
        },
    )
    def export_run(run_id: str | None = None):
        run = captured_export(run_id)
        return Response(
            run.bundle(),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="edge-relative-{run.run_id}.zip"',
                "Cache-Control": "no-store",
                "X-Export-Run-Id": run.run_id,
            },
        )

    @app.get(
        "/api/v1/exports/{symbol}.csv",
        response_class=Response,
        responses={
            200: {"content": {"text/csv": {"schema": {"type": "string"}}}},
            404: {"description": "No loaded chart"},
            409: {"description": "Run replaced"},
        },
    )
    def export(symbol: str, run_id: str | None = None):
        run = captured_export(run_id)
        if symbol not in run.charts:
            raise HTTPException(404, "No chart for this symbol; fetch history first.")
        return Response(
            run.csv(symbol),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{safe_filename(symbol)}-{run.run_id}.csv"',
                "Cache-Control": "no-store",
                "X-Export-Run-Id": run.run_id,
            },
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
