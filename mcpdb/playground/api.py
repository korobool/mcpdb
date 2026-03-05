"""FastAPI application for the MCPDB Playground.

REST endpoints for source management and config.
WebSocket endpoint for streaming query execution.
Static file serving for the built React SPA.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from mcpdb import __version__
from mcpdb.config import McpdbConfig
from mcpdb.sources.registry import SourceRegistry, SourceNotFoundError

logger = logging.getLogger("mcpdb.playground")

STATIC_DIR = Path(__file__).parent / "static"


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class DatabaseConnectRequest(BaseModel):
    connection_string: str
    display_name: str | None = None


class LLMConfigUpdate(BaseModel):
    provider: str
    model: str
    api_key: str = ""


# ---------------------------------------------------------------------------
# App state (module-level, set by create_app)
# ---------------------------------------------------------------------------

_registry: SourceRegistry | None = None
_config: McpdbConfig | None = None
_llm: Any = None
_active_task: asyncio.Task | None = None


def create_app(config: McpdbConfig | None = None) -> FastAPI:
    """Create and configure the FastAPI app."""
    global _registry, _config, _llm

    from mcpdb.config import load_config
    _config = config or load_config()
    _registry = SourceRegistry()

    # Create LLM provider from config
    from mcpdb.llm.factory import create_provider
    llm_cfg = _config.llm.reasoning
    try:
        _llm = create_provider(llm_cfg.provider, llm_cfg.model, llm_cfg.api_key)
    except Exception as e:
        logger.warning("Failed to create LLM provider: %s", e)
        _llm = None

    # Auto-connect database from MCPDB_DATABASE_URL if set
    import os
    db_url = os.environ.get("MCPDB_DATABASE_URL")
    if db_url:
        try:
            from mcpdb.sources.database.source import DatabaseSource
            source = DatabaseSource(db_url)
            _registry.add_source(source)
            logger.info("Auto-connected database from MCPDB_DATABASE_URL")
        except Exception as e:
            logger.warning("Failed to auto-connect MCPDB_DATABASE_URL: %s", e)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        if _registry:
            _registry.close_all()

    app = FastAPI(title="MCPDB Playground", version=__version__, lifespan=lifespan)

    # --- Health -----------------------------------------------------------

    @app.get("/api/health")
    async def health():
        return {
            "version": __version__,
            "source_count": len(_registry) if _registry else 0,
            "llm_provider": llm_cfg.provider,
            "llm_model": llm_cfg.model,
        }

    # --- Sources ----------------------------------------------------------

    @app.get("/api/sources")
    async def list_sources():
        if not _registry:
            return []
        return [m.to_dict() for m in _registry.list_sources()]

    @app.post("/api/sources/database")
    async def connect_database(req: DatabaseConnectRequest):
        from mcpdb.sources.database.source import DatabaseSource
        try:
            source = DatabaseSource(
                req.connection_string,
                display_name=req.display_name,
            )
            source_id = _registry.add_source(source)
            return {"source_id": source_id, "metadata": source.get_metadata().to_dict()}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/api/sources/csv")
    async def upload_csv(file: UploadFile = File(...), display_name: str = Form("")):
        import tempfile, shutil
        try:
            from mcpdb.sources.csv.source import CSVSource
        except ImportError:
            raise HTTPException(status_code=400, detail="CSV support not installed. Install with: pip install mcpdb[csv]")

        suffix = Path(file.filename or "upload.csv").suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = tmp.name

        try:
            source = CSVSource(tmp_path, display_name=display_name or file.filename)
            source_id = _registry.add_source(source)
            return {"source_id": source_id, "metadata": source.get_metadata().to_dict()}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/api/sources/excel")
    async def upload_excel(file: UploadFile = File(...), display_name: str = Form("")):
        import tempfile, shutil
        try:
            from mcpdb.sources.excel.source import ExcelSource
        except ImportError:
            raise HTTPException(status_code=400, detail="Excel support not installed. Install with: pip install mcpdb[excel]")

        suffix = Path(file.filename or "upload.xlsx").suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = tmp.name

        try:
            source = ExcelSource(tmp_path, display_name=display_name or file.filename)
            source_id = _registry.add_source(source)
            return {"source_id": source_id, "metadata": source.get_metadata().to_dict()}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.delete("/api/sources/{source_id}")
    async def remove_source(source_id: str):
        try:
            _registry.remove_source(source_id)
            return {"status": "removed", "source_id": source_id}
        except SourceNotFoundError:
            raise HTTPException(status_code=404, detail=f"Source '{source_id}' not found")

    @app.get("/api/sources/{source_id}")
    async def get_source(source_id: str):
        meta = _registry.get_metadata(source_id)
        if meta is None:
            raise HTTPException(status_code=404, detail=f"Source '{source_id}' not found")
        return meta.to_dict()

    @app.get("/api/sources/{source_id}/sample/{table}")
    async def get_sample(source_id: str, table: str, limit: int = 10):
        source = _registry.get_source(source_id)
        from mcpdb.sources.base import QueryableSource
        if not isinstance(source, QueryableSource):
            raise HTTPException(status_code=400, detail="Source does not support sampling")
        try:
            df = source.get_sample(table, limit=min(limit, 100))
            return {
                "columns": list(df.columns),
                "rows": df.fillna("").to_dict(orient="records"),
                "total_rows": len(df),
            }
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    # --- LLM Config -------------------------------------------------------

    @app.get("/api/config/llm")
    async def get_llm_config():
        cfg = _config.llm.reasoning
        return {
            "provider": cfg.provider,
            "model": cfg.model,
            "has_key": bool(cfg.api_key),
        }

    @app.put("/api/config/llm")
    async def update_llm_config(req: LLMConfigUpdate):
        global _llm
        from mcpdb.llm.factory import create_provider
        try:
            _llm = create_provider(req.provider, req.model, req.api_key)
            _config.llm.reasoning.provider = req.provider
            _config.llm.reasoning.model = req.model
            if req.api_key:
                _config.llm.reasoning.api_key = req.api_key
            return {"status": "updated", "provider": req.provider, "model": req.model}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/api/config/providers")
    async def get_providers():
        return {
            "providers": [
                {
                    "name": "gemini",
                    "display_name": "Google Gemini",
                    "models": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash"],
                    "env_key": "GEMINI_API_KEY",
                },
                {
                    "name": "openai",
                    "display_name": "OpenAI",
                    "models": ["gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano", "o4-mini"],
                    "env_key": "OPENAI_API_KEY",
                },
                {
                    "name": "anthropic",
                    "display_name": "Anthropic",
                    "models": ["claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
                    "env_key": "ANTHROPIC_API_KEY",
                },
                {
                    "name": "ollama",
                    "display_name": "Ollama (Local)",
                    "models": ["llama3.1", "codellama", "mistral"],
                    "env_key": None,
                },
            ]
        }

    # --- WebSocket --------------------------------------------------------

    @app.websocket("/ws/query")
    async def ws_query(ws: WebSocket):
        await ws.accept()
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    await ws.send_json({"type": "error", "message": "Invalid JSON"})
                    continue

                msg_type = msg.get("type")

                if msg_type == "cancel":
                    await _handle_cancel(ws)
                elif msg_type == "query":
                    await _handle_query(ws, msg)
                else:
                    await ws.send_json({"type": "error", "message": f"Unknown type: {msg_type}"})

        except WebSocketDisconnect:
            logger.debug("WebSocket client disconnected")

    async def _handle_cancel(ws: WebSocket):
        global _active_task
        if _active_task and not _active_task.done():
            _active_task.cancel()
            await ws.send_json({"type": "cancelled"})
        else:
            await ws.send_json({"type": "error", "message": "No active query"})

    async def _handle_query(ws: WebSocket, msg: dict):
        global _active_task

        question = msg.get("question", "").strip()
        if not question:
            await ws.send_json({"type": "error", "message": "Empty question"})
            return

        if not _registry or len(_registry) == 0:
            await ws.send_json({"type": "error", "message": "No data sources connected"})
            return

        if not _llm:
            await ws.send_json({"type": "error", "message": "No LLM provider configured"})
            return

        mode_override = msg.get("mode_override")

        # Create async queue for bridging sync callbacks → async WebSocket
        event_queue: asyncio.Queue = asyncio.Queue()

        def on_event(event):
            """Sync callback → puts event into async queue."""
            event_queue.put_nowait({
                "type": "event",
                "event_type": event.type,
                "data": _sanitize(event.data),
                "timestamp": event.timestamp,
            })

        from mcpdb.agent.callbacks import CallbackManager
        from mcpdb.agent.graph import run_agent

        callbacks = CallbackManager()
        callbacks.add_listener(on_event)

        # Run agent in a task so we can forward events as they arrive
        async def run_and_signal():
            try:
                state = await run_agent(
                    question, _registry, _llm, callbacks,
                    mode_override=mode_override,
                )
                # Signal completion via queue
                event_queue.put_nowait({
                    "type": "result",
                    "response": state.get("response", ""),
                    "artifacts": _sanitize_list(state.get("artifacts", [])),
                    "execution_log": _sanitize_list(state.get("execution_log", [])),
                    "query_mode": state.get("query_mode", ""),
                })
            except asyncio.CancelledError:
                event_queue.put_nowait({"type": "cancelled"})
            except Exception as e:
                logger.exception("Agent error")
                event_queue.put_nowait({"type": "error", "message": str(e)})

        _active_task = asyncio.create_task(run_and_signal())

        # Forward events to WebSocket until result/error
        while True:
            item = await event_queue.get()
            try:
                await ws.send_json(item)
            except Exception:
                _active_task.cancel()
                return
            if item["type"] in ("result", "error", "cancelled"):
                break

        _active_task = None

    # --- SPA serving -------------------------------------------------------

    # Mount static files if they exist
    if STATIC_DIR.is_dir() and any(STATIC_DIR.iterdir()):
        app.mount("/playground/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="playground-assets")

        @app.get("/playground/{path:path}")
        async def serve_spa(path: str = ""):
            # Try to serve the exact file first
            file_path = STATIC_DIR / path
            if path and file_path.is_file():
                return FileResponse(file_path)
            # Fall back to index.html for SPA routing
            index = STATIC_DIR / "index.html"
            if index.is_file():
                return FileResponse(index)
            raise HTTPException(status_code=404, detail="Frontend not built")

        @app.get("/playground")
        async def playground_root():
            index = STATIC_DIR / "index.html"
            if index.is_file():
                return FileResponse(index)
            raise HTTPException(status_code=404, detail="Frontend not built. Run: cd frontend && npm run build")
    else:
        @app.get("/playground")
        @app.get("/playground/{path:path}")
        async def playground_not_built(path: str = ""):
            return HTMLResponse(
                "<h2>Frontend not built</h2><p>Run: <code>cd frontend && npm run build</code></p>",
                status_code=404,
            )

    return app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sanitize(data: dict) -> dict:
    """Ensure data is JSON-serializable."""
    result = {}
    for k, v in data.items():
        try:
            json.dumps(v)
            result[k] = v
        except (TypeError, ValueError):
            result[k] = str(v)
    return result


def _sanitize_list(items: list) -> list:
    """Sanitize a list of dicts for JSON."""
    return [_sanitize(item) if isinstance(item, dict) else item for item in items]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def find_available_port(start: int = 8080, end: int = 8180) -> int:
    """Find an available TCP port in the given range."""
    import socket
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No available port in range {start}-{end}")


def run_playground(config: McpdbConfig | None = None, port: int = 8080, open_browser: bool = True) -> None:
    """Start the playground server."""
    import uvicorn

    app = create_app(config)

    if open_browser:
        import threading
        import webbrowser

        def _open():
            import time
            time.sleep(1.5)
            webbrowser.open(f"http://localhost:{port}/playground")

        threading.Thread(target=_open, daemon=True).start()

    logger.info("Starting playground on http://localhost:%d/playground", port)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
