"""Tests for the MCPDB Playground REST API."""

from __future__ import annotations

import pytest

try:
    from fastapi.testclient import TestClient
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

pytestmark = pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")


@pytest.fixture
def client():
    """Create a test client with a fresh app."""
    from mcpdb.playground.api import create_app
    from mcpdb.config import McpdbConfig

    config = McpdbConfig()
    # Use anthropic as provider since it won't actually be called in tests
    config.llm.reasoning.provider = "gemini"
    config.llm.reasoning.model = "gemini-2.5-pro"

    app = create_app(config)
    return TestClient(app)


class TestHealth:
    def test_health_endpoint(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "version" in data
        assert data["source_count"] == 0

    def test_health_has_llm_info(self, client):
        resp = client.get("/api/health")
        data = resp.json()
        assert "llm_provider" in data
        assert "llm_model" in data


class TestSources:
    def test_list_sources_empty(self, client):
        resp = client.get("/api/sources")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_connect_database_sqlite(self, client, tmp_path):
        db_path = tmp_path / "test.db"
        # Create a minimal SQLite DB
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO users VALUES (1, 'Alice')")
        conn.commit()
        conn.close()

        resp = client.post("/api/sources/database", json={
            "connection_string": f"sqlite:///{db_path}",
            "display_name": "Test DB",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "source_id" in data
        assert data["metadata"]["display_name"] == "Test DB"
        assert len(data["metadata"]["tables"]) == 1
        assert data["metadata"]["tables"][0]["name"] == "users"

    def test_connect_and_list(self, client, tmp_path):
        db_path = tmp_path / "test.db"
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.commit()
        conn.close()

        client.post("/api/sources/database", json={
            "connection_string": f"sqlite:///{db_path}",
        })
        resp = client.get("/api/sources")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_remove_source(self, client, tmp_path):
        db_path = tmp_path / "test.db"
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.commit()
        conn.close()

        resp = client.post("/api/sources/database", json={
            "connection_string": f"sqlite:///{db_path}",
        })
        source_id = resp.json()["source_id"]

        resp = client.delete(f"/api/sources/{source_id}")
        assert resp.status_code == 200

        resp = client.get("/api/sources")
        assert resp.json() == []

    def test_remove_nonexistent(self, client):
        resp = client.delete("/api/sources/nonexistent")
        assert resp.status_code == 404

    def test_get_source_metadata(self, client, tmp_path):
        db_path = tmp_path / "test.db"
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, price REAL)")
        conn.commit()
        conn.close()

        resp = client.post("/api/sources/database", json={
            "connection_string": f"sqlite:///{db_path}",
        })
        source_id = resp.json()["source_id"]

        resp = client.get(f"/api/sources/{source_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["source_id"] == source_id
        assert len(data["tables"]) == 1

    def test_get_sample(self, client, tmp_path):
        db_path = tmp_path / "test.db"
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE people (id INTEGER PRIMARY KEY, name TEXT)")
        for i in range(10):
            conn.execute("INSERT INTO people VALUES (?, ?)", (i, f"Person {i}"))
        conn.commit()
        conn.close()

        resp = client.post("/api/sources/database", json={
            "connection_string": f"sqlite:///{db_path}",
        })
        source_id = resp.json()["source_id"]

        resp = client.get(f"/api/sources/{source_id}/sample/people?limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert data["columns"] == ["id", "name"]
        assert len(data["rows"]) == 5

    def test_connect_invalid_db(self, client):
        resp = client.post("/api/sources/database", json={
            "connection_string": "postgresql://invalid:5432/nonexistent",
        })
        assert resp.status_code == 400


class TestConfig:
    def test_get_llm_config(self, client):
        resp = client.get("/api/config/llm")
        assert resp.status_code == 200
        data = resp.json()
        assert "provider" in data
        assert "model" in data
        assert "has_key" in data

    def test_get_providers(self, client):
        resp = client.get("/api/config/providers")
        assert resp.status_code == 200
        data = resp.json()
        assert "providers" in data
        names = {p["name"] for p in data["providers"]}
        assert "gemini" in names
        assert "openai" in names
        assert "anthropic" in names
        assert "ollama" in names

    def test_update_llm_invalid_provider(self, client):
        resp = client.put("/api/config/llm", json={
            "provider": "nonexistent",
            "model": "foo",
        })
        assert resp.status_code == 400


class TestSPA:
    def test_playground_serves_html(self, client):
        resp = client.get("/playground")
        # Either serves the SPA or returns 404 with "not built" message
        assert resp.status_code in (200, 404)

    def test_playground_subpath(self, client):
        resp = client.get("/playground/some/path")
        assert resp.status_code in (200, 404)
