"""MCPDB Web — FastAPI + WebSocket web client.

Direct agent access with real-time event streaming.
No React, no npm, no build step. Just Python serving HTML.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    UploadFile,
    File,
    Form,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from mcpdb import __version__
from mcpdb.config import McpdbConfig
from mcpdb.sources.registry import SourceRegistry, SourceNotFoundError

logger = logging.getLogger("mcpdb.web")

TEMPLATE_DIR = Path(__file__).parent / "templates"


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

MAX_UPLOAD_SIZE_MB = 500  # Max file upload size in MB


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
_experience_service: Any = None
_active_tasks: dict[int, asyncio.Task] = {}  # ws_id → task (per-connection)
_ws_counter: int = 0
_no_cache: bool = False


def create_app(config: McpdbConfig | None = None, no_cache: bool = False) -> FastAPI:
    """Create and configure the FastAPI app."""
    global _registry, _config, _llm, _experience_service, _no_cache
    _no_cache = no_cache

    from mcpdb.config import load_config
    _config = config or load_config()
    _registry = SourceRegistry()

    # Create LLM provider
    from mcpdb.llm.factory import create_provider
    llm_cfg = _config.llm.reasoning
    try:
        _llm = create_provider(llm_cfg.provider, llm_cfg.model, llm_cfg.api_key)
    except Exception as e:
        logger.warning("Failed to create LLM provider: %s", e)
        _llm = None

    # Experience service
    from mcpdb.experience.service import ExperienceService
    _experience_service = ExperienceService(_config.experience)

    # Pass env DB URL to template for pre-filling (don't auto-connect)
    _prefill_db_url = os.environ.get("MCPDB_DATABASE_URL", "")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if _experience_service is not None:
            await _experience_service.start(_llm)
        yield
        if _experience_service is not None:
            await _experience_service.stop()
        if _registry:
            _registry.close_all()

    app = FastAPI(title="MCPDB", version=__version__, lifespan=lifespan)
    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

    # --- Main page --------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse(request, "index.html", {
            "version": __version__,
            "prefill_db_url": _prefill_db_url,
        })

    # --- Favicon ----------------------------------------------------------

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        from fastapi.responses import Response
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
            'stroke="%232563eb" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
            '<ellipse cx="12" cy="5" rx="9" ry="3"/>'
            '<path d="M3 5V19A9 3 0 0 0 21 19V5"/>'
            '<path d="M3 12A9 3 0 0 0 21 12"/>'
            '</svg>'
        )
        return Response(content=svg, media_type="image/svg+xml")

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
        sources = []
        for m in _registry.list_sources():
            d = m.to_dict()
            # Add table summary for the frontend
            d["table_summary"] = [
                {
                    "name": t["name"],
                    "columns": len(t.get("columns", [])),
                    "rows": t.get("row_count"),
                }
                for t in d.get("tables", [])
            ]
            sources.append(d)
        return sources

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
    async def upload_csv(
        files: list[UploadFile] = File(...),
        display_name: str = Form(""),
    ):
        import tempfile, shutil
        try:
            from mcpdb.sources.csv.source import CsvSource
        except ImportError:
            raise HTTPException(status_code=400, detail="CSV support not installed. Install with: pip install mcpdb[csv]")

        # Save uploaded files to temp directory
        tmp_paths = []
        filenames = []
        try:
            for f in files:
                suffix = Path(f.filename or "upload.csv").suffix
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    shutil.copyfileobj(f.file, tmp)
                    # Check file size
                    size_mb = Path(tmp.name).stat().st_size / (1024 * 1024)
                    if size_mb > MAX_UPLOAD_SIZE_MB:
                        Path(tmp.name).unlink(missing_ok=True)
                        raise HTTPException(
                            status_code=413,
                            detail=f"File '{f.filename}' is {size_mb:.0f}MB, max is {MAX_UPLOAD_SIZE_MB}MB",
                        )
                    tmp_paths.append(tmp.name)
                    filenames.append(f.filename or "upload.csv")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"File upload failed: {e}")

        try:
            name = display_name or ", ".join(filenames[:3])
            if len(filenames) > 3:
                name += f" (+{len(filenames) - 3} more)"
            # Use original filenames (without extension) as table names
            from mcpdb.sources.csv.loader import _make_table_name
            table_names = [_make_table_name(fn) for fn in filenames]
            source = CsvSource(tmp_paths, display_name=name, table_names=table_names)
            source_id = _registry.add_source(source)
            return {"source_id": source_id, "metadata": source.get_metadata().to_dict()}
        except Exception as e:
            # Clean up temp files on source creation failure
            for p in tmp_paths:
                try:
                    Path(p).unlink(missing_ok=True)
                except Exception:
                    pass
            logger.exception("CSV source creation failed")
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/api/sources/excel")
    async def upload_excel(file: UploadFile = File(...), display_name: str = Form("")):
        import tempfile, shutil
        try:
            from mcpdb.sources.excel.source import ExcelSource
        except ImportError:
            raise HTTPException(status_code=400, detail="Excel support not installed")

        suffix = Path(file.filename or "upload.xlsx").suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = tmp.name

        size_mb = Path(tmp_path).stat().st_size / (1024 * 1024)
        if size_mb > MAX_UPLOAD_SIZE_MB:
            Path(tmp_path).unlink(missing_ok=True)
            raise HTTPException(
                status_code=413,
                detail=f"File is {size_mb:.0f}MB, max is {MAX_UPLOAD_SIZE_MB}MB",
            )

        try:
            source = ExcelSource(tmp_path, display_name=display_name or file.filename)
            source_id = _registry.add_source(source)
            return {"source_id": source_id, "metadata": source.get_metadata().to_dict()}
        except Exception as e:
            Path(tmp_path).unlink(missing_ok=True)
            logger.exception("Excel source creation failed")
            raise HTTPException(status_code=400, detail=str(e))

    @app.delete("/api/sources/{source_id}")
    async def remove_source(source_id: str):
        try:
            _registry.remove_source(source_id)
            return {"status": "removed"}
        except SourceNotFoundError:
            raise HTTPException(status_code=404, detail="Source not found")

    @app.get("/api/sources/{source_id}/sample/{table}")
    async def get_sample(source_id: str, table: str, limit: int = 10):
        try:
            source = _registry.get_source(source_id)
        except SourceNotFoundError:
            raise HTTPException(status_code=404, detail="Source not found")
        from mcpdb.sources.base import QueryableSource
        if not isinstance(source, QueryableSource):
            raise HTTPException(status_code=400, detail="Source does not support sampling")
        try:
            df = source.get_sample(table, limit=min(limit, 100))
            return {
                "columns": list(df.columns),
                "rows": df.fillna("").to_dict(orient="records"),
            }
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    # --- ERD --------------------------------------------------------------

    @app.get("/api/sources/{source_id}/erd")
    async def get_erd(source_id: str):
        try:
            source = _registry.get_source(source_id)
            tables = source.get_tables()
            relationships = source.get_relationships()
            from mcpdb.mcp.resources import _build_mermaid_erd
            return {"mermaid": _build_mermaid_erd(tables, relationships)}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    # --- LLM Config -------------------------------------------------------

    @app.get("/api/config/llm")
    async def get_llm_config():
        return {
            "provider": llm_cfg.provider,
            "model": llm_cfg.model,
            "has_key": bool(llm_cfg.api_key),
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
            return {"status": "updated"}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    # --- WebSocket: real-time query execution -----------------------------

    @app.websocket("/ws/query")
    async def ws_query(ws: WebSocket):
        global _ws_counter
        _ws_counter += 1
        ws_id = _ws_counter
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
                    await _handle_cancel(ws, ws_id)
                elif msg_type == "query":
                    await _handle_query(ws, msg, ws_id)
                else:
                    await ws.send_json({"type": "error", "message": f"Unknown: {msg_type}"})
        except WebSocketDisconnect:
            logger.debug("WebSocket %d disconnected", ws_id)
            # Cancel any running task for this connection
            task = _active_tasks.pop(ws_id, None)
            if task and not task.done():
                task.cancel()

    async def _handle_cancel(ws: WebSocket, ws_id: int):
        task = _active_tasks.get(ws_id)
        if task and not task.done():
            task.cancel()
            await ws.send_json({"type": "cancelled"})
        else:
            await ws.send_json({"type": "error", "message": "No active query"})

    async def _handle_query(ws: WebSocket, msg: dict, ws_id: int):

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

        # Cancel any existing query for this connection
        existing = _active_tasks.pop(ws_id, None)
        if existing and not existing.done():
            existing.cancel()

        mode_override = msg.get("mode")
        if mode_override == "auto":
            mode_override = None
        force_rethink = msg.get("rethink", False)
        # Per-query no_cache override or server-level default
        query_no_cache = msg.get("noCache", _no_cache)

        # Async queue bridges sync agent callbacks → async WebSocket
        event_queue: asyncio.Queue = asyncio.Queue(maxsize=5000)

        def on_event(event):
            try:
                event_queue.put_nowait({
                    "type": "event",
                    "event_type": event.type,
                    "data": _sanitize(event.data),
                    "timestamp": event.timestamp,
                })
            except asyncio.QueueFull:
                pass  # Drop events rather than block — graceful degradation

        from mcpdb.agent.callbacks import CallbackManager
        from mcpdb.agent.cancellation import CancellationToken
        from mcpdb.agent.graph import run_agent
        from mcpdb.mcp.tools.analysis import _generate_followups_inline

        callbacks = CallbackManager()
        callbacks.add_listener(on_event)
        cancellation_token = CancellationToken()

        exp_cache = _experience_service.cache if _experience_service else None
        exp_staging = _experience_service.staging if _experience_service else None

        async def run_and_signal():
            try:
                state = await asyncio.wait_for(
                    run_agent(
                        question, _registry, _llm, callbacks,
                        mode_override=mode_override,
                        experience_cache=exp_cache,
                        force_rethink=force_rethink,
                        staging_store=exp_staging,
                        no_cache=query_no_cache,
                        cancellation_token=cancellation_token,
                    ),
                    timeout=600.0,  # 10-minute hard timeout per query
                )
                # Generate follow-up suggestions (best-effort, non-blocking)
                followups = await _safe_generate_followups(
                    _registry, _llm, question,
                    state.get("response", ""),
                )

                event_queue.put_nowait({
                    "type": "result",
                    "response": state.get("response", ""),
                    "artifacts": _sanitize_list(state.get("artifacts", [])),
                    "execution_log": _sanitize_list(state.get("execution_log", [])),
                    "query_mode": state.get("query_mode", ""),
                    "followups": followups,
                })
            except asyncio.TimeoutError:
                event_queue.put_nowait({
                    "type": "error",
                    "message": "Query timed out after 10 minutes. Try a simpler question or use a specific mode.",
                })
            except asyncio.CancelledError:
                event_queue.put_nowait({"type": "cancelled"})
            except Exception as e:
                logger.exception("Agent error")
                event_queue.put_nowait({"type": "error", "message": str(e)})

        task = asyncio.create_task(run_and_signal())
        _active_tasks[ws_id] = task

        # Stream events to browser as they arrive
        while True:
            item = await event_queue.get()
            try:
                await ws.send_json(item)
            except Exception:
                task.cancel()
                _active_tasks.pop(ws_id, None)
                return
            if item["type"] in ("result", "error", "cancelled"):
                break

        _active_tasks.pop(ws_id, None)

    return app


# ---------------------------------------------------------------------------
# Follow-up generation with fallback
# ---------------------------------------------------------------------------

async def _safe_generate_followups(
    registry: SourceRegistry,
    llm: Any,
    question: str,
    response: str,
) -> list[str]:
    """Generate follow-ups with LLM, falling back to response-based suggestions."""
    from mcpdb.mcp.tools.analysis import _generate_followups_inline

    # Try LLM-based generation
    try:
        followups = await _generate_followups_inline(registry, llm, question)
        if followups:
            logger.debug("LLM follow-ups (%d) for: %s", len(followups), question[:60])
            return followups
    except Exception as e:
        logger.debug("LLM follow-up generation failed: %s", e)

    # Fallback: generate from response context
    return _fallback_followups(question, response, registry)


def _fallback_followups(
    question: str, response: str, registry: SourceRegistry,
) -> list[str]:
    """Generate simple follow-up suggestions from response context."""
    followups = []
    q_lower = question.lower()

    # Context-aware follow-ups based on question patterns
    if any(w in q_lower for w in ("how many", "count", "total")):
        followups.append("How has this changed over time?")
        followups.append("Which category has the highest count?")
    elif any(w in q_lower for w in ("average", "mean", "median")):
        followups.append("What is the distribution of these values?")
        followups.append("Are there any outliers?")
    elif any(w in q_lower for w in ("top", "highest", "most", "best")):
        followups.append("What about the bottom performers?")
        followups.append("How do these compare to the overall average?")
    elif any(w in q_lower for w in ("trend", "over time", "by month", "by year")):
        followups.append("What is driving this trend?")
        followups.append("Are there seasonal patterns?")

    # Always add some generic useful follow-ups
    if not followups:
        followups.append("Can you break this down by category?")
        followups.append("What are the key trends in this data?")

    followups.append("What other insights can you find?")

    return followups[:4]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sanitize(data: dict) -> dict:
    result = {}
    for k, v in data.items():
        try:
            json.dumps(v)
            result[k] = v
        except (TypeError, ValueError):
            result[k] = str(v)
    return result


def _sanitize_list(items: list) -> list:
    return [_sanitize(item) if isinstance(item, dict) else item for item in items]


def find_available_port(start: int = 8080, end: int = 8180) -> int:
    import socket
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No available port in range {start}-{end}")


def run_web(config: McpdbConfig | None = None, port: int = 8080, open_browser: bool = True, no_cache: bool = False) -> None:
    """Start the MCPDB web client."""
    import uvicorn

    app = create_app(config, no_cache=no_cache)

    if open_browser:
        import threading
        import webbrowser

        def _open():
            time.sleep(1.5)
            webbrowser.open(f"http://localhost:{port}")

        threading.Thread(target=_open, daemon=True).start()

    logger.info("Starting MCPDB web on http://localhost:%d", port)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
