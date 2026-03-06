"""Tests for the MCPDB web client (FastAPI backend)."""

from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


@pytest.fixture
def app():
    """Create a test app with mocked LLM and no database."""
    with patch("mcpdb.llm.factory.create_provider") as mock_create:
        mock_create.return_value = MagicMock()
        from mcpdb.web.app import create_app
        yield create_app()


@pytest.fixture
def client(app):
    return TestClient(app)


class TestHealth:
    def test_health_endpoint(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "version" in data
        assert "source_count" in data

    def test_index_page(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "MCPDB" in resp.text
        assert "WebSocket" in resp.text

    def test_favicon(self, client):
        resp = client.get("/favicon.ico")
        assert resp.status_code == 200
        assert "svg" in resp.text


class TestSources:
    def test_list_sources_empty(self, client):
        resp = client.get("/api/sources")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_connect_database_invalid(self, client):
        resp = client.post("/api/sources/database", json={
            "connection_string": "invalid://nope",
        })
        assert resp.status_code == 400

    def test_connect_database_sqlite(self, client, tmp_path):
        db_path = tmp_path / "test.db"
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO test VALUES (1, 'hello')")
        conn.commit()
        conn.close()

        resp = client.post("/api/sources/database", json={
            "connection_string": f"sqlite:///{db_path}",
            "display_name": "testdb",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "source_id" in data
        assert "metadata" in data

        # Verify it shows up in list
        resp = client.get("/api/sources")
        sources = resp.json()
        assert len(sources) == 1
        assert sources[0]["display_name"] == "testdb"
        assert "table_summary" in sources[0]

    def test_remove_source_not_found(self, client):
        resp = client.delete("/api/sources/nonexistent")
        assert resp.status_code == 404


class TestERD:
    def test_erd_with_source(self, client, tmp_path):
        db_path = tmp_path / "erd_test.db"
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER)")
        conn.commit()
        conn.close()

        client.post("/api/sources/database", json={
            "connection_string": f"sqlite:///{db_path}",
        })

        sources = client.get("/api/sources").json()
        sid = sources[0]["source_id"]

        resp = client.get(f"/api/sources/{sid}/erd")
        assert resp.status_code == 200
        data = resp.json()
        assert "mermaid" in data
        assert "erDiagram" in data["mermaid"]


class TestWebSocket:
    def test_ws_empty_question(self, client):
        with client.websocket_connect("/ws/query") as ws:
            ws.send_json({"type": "query", "question": ""})
            resp = ws.receive_json()
            assert resp["type"] == "error"
            assert "Empty" in resp["message"]

    def test_ws_no_sources(self, client):
        with client.websocket_connect("/ws/query") as ws:
            ws.send_json({"type": "query", "question": "test"})
            resp = ws.receive_json()
            assert resp["type"] == "error"
            assert "sources" in resp["message"].lower()

    def test_ws_unknown_type(self, client):
        with client.websocket_connect("/ws/query") as ws:
            ws.send_json({"type": "garbage"})
            resp = ws.receive_json()
            assert resp["type"] == "error"

    def test_ws_invalid_json(self, client):
        with client.websocket_connect("/ws/query") as ws:
            ws.send_text("not json at all")
            resp = ws.receive_json()
            assert resp["type"] == "error"
            assert "JSON" in resp["message"]

    def test_ws_cancel_no_query(self, client):
        with client.websocket_connect("/ws/query") as ws:
            ws.send_json({"type": "cancel"})
            resp = ws.receive_json()
            assert resp["type"] == "error"
            assert "No active" in resp["message"]


class TestLLMConfig:
    def test_get_config(self, client):
        resp = client.get("/api/config/llm")
        assert resp.status_code == 200
        data = resp.json()
        assert "provider" in data
        assert "model" in data
