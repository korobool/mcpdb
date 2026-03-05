"""Tests for the centralized ExperienceService."""

from __future__ import annotations

import asyncio
import tempfile

import pytest

from mcpdb.config import ExperienceConfig
from mcpdb.experience.service import ExperienceService


@pytest.fixture
def temp_config(tmp_path):
    """Create an ExperienceConfig pointing to a temp directory."""
    return ExperienceConfig(
        storage_dir=str(tmp_path / "experience"),
        quality_eval_enabled=True,
        quality_eval_min_score=7,
        quality_eval_poll_interval=1.0,
        quality_eval_max_retries=1,
    )


@pytest.fixture
def disabled_config(tmp_path):
    """Config with quality eval disabled."""
    return ExperienceConfig(
        storage_dir=str(tmp_path / "experience"),
        quality_eval_enabled=False,
    )


class TestExperienceService:
    def test_init_creates_components(self, temp_config):
        service = ExperienceService(temp_config)
        assert service.store is not None
        assert service.cache is not None
        assert service.staging is not None
        assert not service.is_running

    def test_init_default_config(self):
        service = ExperienceService()
        assert service.store is not None
        assert service.cache is not None
        assert service.staging is not None

    def test_worker_stats_no_worker(self, temp_config):
        service = ExperienceService(temp_config)
        stats = service.worker_stats
        assert stats == {"promoted": 0, "rejected": 0, "errors": 0}

    @pytest.mark.asyncio
    async def test_start_disabled(self, disabled_config):
        service = ExperienceService(disabled_config)
        await service.start(llm=object())
        assert not service.is_running
        await service.stop()

    @pytest.mark.asyncio
    async def test_start_no_llm(self, temp_config):
        service = ExperienceService(temp_config)
        await service.start(llm=None)
        assert not service.is_running
        await service.stop()

    @pytest.mark.asyncio
    async def test_stop_idempotent(self, temp_config):
        service = ExperienceService(temp_config)
        # Calling stop without start should be safe
        await service.stop()
        await service.stop()

    def test_store_and_cache_share_store(self, temp_config):
        service = ExperienceService(temp_config)
        assert service.cache._store is service.store

    def test_staging_dir_created(self, temp_config):
        service = ExperienceService(temp_config)
        assert service.staging._staging_dir.exists()
