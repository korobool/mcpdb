"""Tests for v3.8.x — Session Persistence (disk storage, multi-session, import/export)."""

from __future__ import annotations

import json
import time

import pytest

from mcpdb.session.session_manager import SessionData, SessionManager


class TestSessionData:
    def test_defaults(self):
        s = SessionData(session_id="abc", created_at=1.0, last_active=1.0)
        assert s.sources == []
        assert s.messages == []
        assert s.metadata == {}

    def test_to_dict(self):
        s = SessionData(session_id="abc", created_at=1.0, last_active=2.0)
        d = s.to_dict()
        assert d["session_id"] == "abc"
        assert d["created_at"] == 1.0

    def test_from_dict(self):
        d = {
            "session_id": "xyz",
            "created_at": 1.0,
            "last_active": 2.0,
            "sources": [{"type": "db"}],
            "messages": [{"role": "user", "content": "hello"}],
        }
        s = SessionData.from_dict(d)
        assert s.session_id == "xyz"
        assert len(s.sources) == 1
        assert len(s.messages) == 1

    def test_roundtrip(self):
        original = SessionData(
            session_id="test",
            created_at=100.0,
            last_active=200.0,
            metadata={"key": "value"},
        )
        restored = SessionData.from_dict(original.to_dict())
        assert restored.session_id == original.session_id
        assert restored.metadata == original.metadata


class TestPersistentSessionManager:
    def test_create_session(self, tmp_path):
        mgr = SessionManager(storage_dir=str(tmp_path))
        session = mgr.create_session()
        assert session.session_id
        assert session.created_at > 0

    def test_get_session(self, tmp_path):
        mgr = SessionManager(storage_dir=str(tmp_path))
        session = mgr.create_session()
        retrieved = mgr.get_session(session.session_id)
        assert retrieved is not None
        assert retrieved.session_id == session.session_id

    def test_get_nonexistent(self, tmp_path):
        mgr = SessionManager(storage_dir=str(tmp_path))
        assert mgr.get_session("nonexistent") is None

    def test_update_session(self, tmp_path):
        mgr = SessionManager(storage_dir=str(tmp_path))
        session = mgr.create_session()
        mgr.update_session(
            session.session_id,
            messages=[{"role": "user", "content": "test"}],
        )
        updated = mgr.get_session(session.session_id)
        assert len(updated.messages) == 1

    def test_update_nonexistent(self, tmp_path):
        mgr = SessionManager(storage_dir=str(tmp_path))
        with pytest.raises(KeyError):
            mgr.update_session("bad", messages=[])

    def test_close_session(self, tmp_path):
        mgr = SessionManager(storage_dir=str(tmp_path))
        session = mgr.create_session()
        mgr.close_session(session.session_id)
        assert mgr.get_session(session.session_id) is None

    def test_list_sessions(self, tmp_path):
        mgr = SessionManager(storage_dir=str(tmp_path))
        mgr.create_session(metadata={"name": "s1"})
        mgr.create_session(metadata={"name": "s2"})
        sessions = mgr.list_sessions()
        assert len(sessions) == 2

    def test_max_concurrent(self, tmp_path):
        mgr = SessionManager(storage_dir=str(tmp_path), max_concurrent=2)
        mgr.create_session()
        mgr.create_session()
        with pytest.raises(RuntimeError, match="Max concurrent"):
            mgr.create_session()

    def test_export_import(self, tmp_path):
        mgr = SessionManager(storage_dir=str(tmp_path))
        session = mgr.create_session(metadata={"key": "val"})
        mgr.update_session(session.session_id, messages=[{"role": "user", "content": "hi"}])

        exported = mgr.export_session(session.session_id)
        parsed = json.loads(exported)
        assert parsed["session_id"] == session.session_id

        mgr2 = SessionManager(storage_dir=str(tmp_path / "other"))
        imported = mgr2.import_session(exported)
        assert imported.session_id == session.session_id
        assert imported.metadata["key"] == "val"
        assert len(imported.messages) == 1

    def test_export_nonexistent(self, tmp_path):
        mgr = SessionManager(storage_dir=str(tmp_path))
        with pytest.raises(KeyError):
            mgr.export_session("bad")

    def test_session_persists_to_disk(self, tmp_path):
        mgr1 = SessionManager(storage_dir=str(tmp_path))
        session = mgr1.create_session(metadata={"test": True})
        sid = session.session_id

        mgr2 = SessionManager(storage_dir=str(tmp_path))
        restored = mgr2.get_session(sid)
        assert restored is not None
        assert restored.metadata.get("test") is True

    def test_close_deletes_file(self, tmp_path):
        mgr = SessionManager(storage_dir=str(tmp_path))
        session = mgr.create_session()
        mgr.close_session(session.session_id)
        assert not (tmp_path / f"{session.session_id}.json").exists()

    def test_metadata_merge(self, tmp_path):
        mgr = SessionManager(storage_dir=str(tmp_path))
        session = mgr.create_session(metadata={"a": 1})
        mgr.update_session(session.session_id, metadata={"b": 2})
        updated = mgr.get_session(session.session_id)
        assert updated.metadata == {"a": 1, "b": 2}

    def test_session_id_format(self, tmp_path):
        mgr = SessionManager(storage_dir=str(tmp_path))
        session = mgr.create_session()
        assert len(session.session_id) == 8

    def test_sources_update(self, tmp_path):
        mgr = SessionManager(storage_dir=str(tmp_path))
        session = mgr.create_session()
        mgr.update_session(
            session.session_id,
            sources=[{"id": "s1", "type": "database"}],
        )
        updated = mgr.get_session(session.session_id)
        assert len(updated.sources) == 1
        assert updated.sources[0]["type"] == "database"
