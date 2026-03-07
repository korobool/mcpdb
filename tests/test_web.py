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

    def test_no_auto_connect_from_env(self, client):
        """MCPDB_DATABASE_URL should NOT auto-connect, only prefill."""
        resp = client.get("/api/sources")
        assert resp.json() == []  # nothing auto-connected

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


class TestCSVUpload:
    def test_upload_single_csv(self, client, tmp_path):
        csv_path = tmp_path / "sales.csv"
        csv_path.write_text("id,product,amount\n1,Widget,100\n2,Gadget,200\n")

        with open(csv_path, "rb") as f:
            resp = client.post(
                "/api/sources/csv",
                files=[("files", ("sales.csv", f, "text/csv"))],
                data={"display_name": "test-csv"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "source_id" in data
        assert "metadata" in data

        # Verify it shows up in list
        sources = client.get("/api/sources").json()
        assert len(sources) == 1
        assert sources[0]["display_name"] == "test-csv"
        assert sources[0]["source_type"] == "csv"

    def test_upload_multiple_csvs(self, client, tmp_path):
        csv1 = tmp_path / "orders.csv"
        csv1.write_text("order_id,customer,total\n1,Alice,50\n2,Bob,75\n")
        csv2 = tmp_path / "customers.csv"
        csv2.write_text("name,city\nAlice,NYC\nBob,LA\n")

        files = []
        handles = []
        for p in [csv1, csv2]:
            h = open(p, "rb")
            handles.append(h)
            files.append(("files", (p.name, h, "text/csv")))
        try:
            resp = client.post("/api/sources/csv", files=files)
        finally:
            for h in handles:
                h.close()

        assert resp.status_code == 200
        data = resp.json()
        assert "source_id" in data

        # Should have tables for both files
        sources = client.get("/api/sources").json()
        assert len(sources) == 1
        tables = sources[0].get("tables", [])
        assert len(tables) == 2

    def test_upload_csv_no_files(self, client):
        resp = client.post("/api/sources/csv")
        assert resp.status_code == 422  # validation error — no files

    def test_upload_csv_auto_name(self, client, tmp_path):
        csv_path = tmp_path / "data.csv"
        csv_path.write_text("a,b\n1,2\n")

        with open(csv_path, "rb") as f:
            resp = client.post(
                "/api/sources/csv",
                files=[("files", ("data.csv", f, "text/csv"))],
            )
        assert resp.status_code == 200
        sources = client.get("/api/sources").json()
        assert "data.csv" in sources[0]["display_name"]

    def test_remove_csv_source(self, client, tmp_path):
        csv_path = tmp_path / "remove_me.csv"
        csv_path.write_text("x,y\n1,2\n")

        with open(csv_path, "rb") as f:
            resp = client.post(
                "/api/sources/csv",
                files=[("files", ("remove_me.csv", f, "text/csv"))],
            )
        assert resp.status_code == 200
        sid = resp.json()["source_id"]

        resp = client.delete(f"/api/sources/{sid}")
        assert resp.status_code == 200

        sources = client.get("/api/sources").json()
        assert len(sources) == 0

    def test_csv_sample_endpoint(self, client, tmp_path):
        csv_path = tmp_path / "sample_test.csv"
        csv_path.write_text("id,name,value\n1,alpha,10\n2,beta,20\n3,gamma,30\n")

        with open(csv_path, "rb") as f:
            resp = client.post(
                "/api/sources/csv",
                files=[("files", ("sample_test.csv", f, "text/csv"))],
            )
        assert resp.status_code == 200
        sid = resp.json()["source_id"]

        # Get table name from sources list
        sources = client.get("/api/sources").json()
        table_name = sources[0]["tables"][0]["name"]

        resp = client.get(f"/api/sources/{sid}/sample/{table_name}?limit=2")
        assert resp.status_code == 200
        data = resp.json()
        assert "columns" in data
        assert "rows" in data
        assert len(data["rows"]) == 2


class TestLLMConfig:
    def test_get_config(self, client):
        resp = client.get("/api/config/llm")
        assert resp.status_code == 200
        data = resp.json()
        assert "provider" in data
        assert "model" in data
