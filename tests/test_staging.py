"""Tests for staging store and staged records."""

from __future__ import annotations

import json
import time

import pytest

from mcpdb.experience.records import CodeStep, QualityResult, StagedRecord
from mcpdb.experience.staging import StagingStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def staging(tmp_path) -> StagingStore:
    return StagingStore(staging_dir=str(tmp_path / "staging"))


def _make_staged(
    intent_hash: str = "h1",
    question: str = "test question",
    fingerprint: str = "fp_abc",
    mode: str = "simple",
    response: str = "Test response with enough chars",
) -> StagedRecord:
    return StagedRecord(
        intent_hash=intent_hash,
        question=question,
        source_fingerprint=fingerprint,
        schema_hash="sh_abc",
        query_mode=mode,
        steps=[CodeStep(action_type="sql", code="SELECT 1", result_preview="1 row")],
        response=response,
        semantic_hash="sem_h1",
    )


# ---------------------------------------------------------------------------
# StagedRecord tests
# ---------------------------------------------------------------------------

class TestStagedRecord:
    def test_round_trip(self):
        record = _make_staged()
        d = record.to_dict()
        restored = StagedRecord.from_dict(d)

        assert restored.intent_hash == record.intent_hash
        assert restored.question == record.question
        assert restored.query_mode == record.query_mode
        assert restored.evaluated is False
        assert restored.semantic_hash == "sem_h1"
        assert len(restored.steps) == 1

    def test_to_success_record(self):
        record = _make_staged()
        success = record.to_success_record()

        assert success.intent_hash == record.intent_hash
        assert success.question == record.question
        assert success.response == record.response
        assert success.query_mode == record.query_mode
        assert success.semantic_hash == record.semantic_hash
        assert len(success.steps) == len(record.steps)

    def test_type_field(self):
        record = _make_staged()
        d = record.to_dict()
        assert d["type"] == "staged"

    def test_evaluated_flag_serialized(self):
        record = _make_staged()
        record.evaluated = True
        d = record.to_dict()
        assert d["evaluated"] is True

        restored = StagedRecord.from_dict(d)
        assert restored.evaluated is True


# ---------------------------------------------------------------------------
# QualityResult tests
# ---------------------------------------------------------------------------

class TestQualityResult:
    def test_round_trip(self):
        result = QualityResult(
            score=8, completeness=9, accuracy=7,
            relevance=8, clarity=9,
            issues=["minor formatting"],
            verdict="promote",
        )
        d = result.to_dict()
        restored = QualityResult.from_dict(d)

        assert restored.score == 8
        assert restored.completeness == 9
        assert restored.verdict == "promote"
        assert restored.issues == ["minor formatting"]

    def test_defaults(self):
        result = QualityResult(
            score=3, completeness=3, accuracy=3,
            relevance=3, clarity=3,
        )
        assert result.verdict == "reject"
        assert result.issues == []


# ---------------------------------------------------------------------------
# StagingStore tests
# ---------------------------------------------------------------------------

class TestStagingStore:
    def test_stage_and_get_pending(self, staging):
        record = _make_staged()
        staging.stage(record)

        pending = staging.get_pending("fp_abc")
        assert len(pending) == 1
        assert pending[0].intent_hash == "h1"
        assert pending[0].evaluated is False

    def test_multiple_records(self, staging):
        staging.stage(_make_staged(intent_hash="h1"))
        staging.stage(_make_staged(intent_hash="h2"))

        pending = staging.get_pending("fp_abc")
        assert len(pending) == 2

    def test_different_fingerprints_isolated(self, staging):
        staging.stage(_make_staged(intent_hash="h1", fingerprint="fp_a"))
        staging.stage(_make_staged(intent_hash="h2", fingerprint="fp_b"))

        assert len(staging.get_pending("fp_a")) == 1
        assert len(staging.get_pending("fp_b")) == 1
        assert len(staging.get_pending("fp_c")) == 0

    def test_mark_evaluated(self, staging):
        staging.stage(_make_staged(intent_hash="h1"))
        staging.stage(_make_staged(intent_hash="h2"))

        staging.mark_evaluated("fp_abc", "h1")

        pending = staging.get_pending("fp_abc")
        assert len(pending) == 1
        assert pending[0].intent_hash == "h2"

        # h1 is still in all records, just marked evaluated
        all_records = staging.get_all("fp_abc")
        assert len(all_records) == 2

    def test_remove(self, staging):
        staging.stage(_make_staged(intent_hash="h1"))
        staging.stage(_make_staged(intent_hash="h2"))

        staging.remove("fp_abc", "h1")

        all_records = staging.get_all("fp_abc")
        assert len(all_records) == 1
        assert all_records[0].intent_hash == "h2"

    def test_remove_last_record_deletes_file(self, staging):
        staging.stage(_make_staged(intent_hash="h1"))
        staging.remove("fp_abc", "h1")

        # File should be deleted
        path = staging._source_path("fp_abc")
        assert not path.exists()
        assert staging.get_all("fp_abc") == []

    def test_list_fingerprints(self, staging):
        staging.stage(_make_staged(fingerprint="fp_one"))
        staging.stage(_make_staged(fingerprint="fp_two"))

        fps = staging.list_fingerprints()
        assert "fp_one" in fps
        assert "fp_two" in fps

    def test_get_all_pending(self, staging):
        staging.stage(_make_staged(intent_hash="h1", fingerprint="fp_a"))
        staging.stage(_make_staged(intent_hash="h2", fingerprint="fp_b"))
        staging.stage(_make_staged(intent_hash="h3", fingerprint="fp_a"))

        # Mark one as evaluated
        staging.mark_evaluated("fp_a", "h1")

        pending = staging.get_all_pending()
        assert len(pending) == 2
        hashes = {r.intent_hash for r in pending}
        assert hashes == {"h2", "h3"}

    def test_corrupt_record_skipped(self, staging):
        fp = "fp_corrupt"
        path = staging._source_path(fp)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            f.write("not valid json\n")
            f.write(json.dumps(_make_staged(fingerprint=fp).to_dict()) + "\n")

        results = staging.get_all(fp)
        assert len(results) == 1

    def test_empty_fingerprint(self, staging):
        assert staging.get_pending("nonexistent") == []
        assert staging.get_all("nonexistent") == []
