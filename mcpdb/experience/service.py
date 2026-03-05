"""Centralized experience service — owns store, cache, staging, and background worker.

Every entry point (MCP server, Playground, CLI) creates one ExperienceService
instance. The service manages the background quality evaluation worker lifecycle
and provides access to all experience components.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from mcpdb.config import ExperienceConfig
from mcpdb.experience.cache import ExperienceCache
from mcpdb.experience.evaluator import QualityEvaluator
from mcpdb.experience.staging import StagingStore
from mcpdb.experience.store import ExperienceStore
from mcpdb.experience.worker import QualityWorker

logger = logging.getLogger("mcpdb.experience.service")


class ExperienceService:
    """Centralized owner of all experience system components.

    Usage:
        service = ExperienceService(config)
        await service.start(llm)   # starts background worker
        ...
        await service.stop()       # graceful shutdown
    """

    def __init__(self, config: ExperienceConfig | None = None) -> None:
        if config is None:
            config = ExperienceConfig()

        storage_dir = os.path.expanduser(config.storage_dir)
        staging_dir = os.path.join(storage_dir, "staging")

        self.store = ExperienceStore(
            storage_dir=storage_dir,
            max_success=config.max_success_records,
            max_failure=config.max_failure_records,
        )
        self.cache = ExperienceCache(
            store=self.store,
            max_age_days=config.cache_max_age_days,
        )
        self.staging = StagingStore(staging_dir=staging_dir)

        self._config = config
        self._worker: QualityWorker | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self, llm: Any) -> None:
        """Start the background quality evaluation worker.

        No-op if quality_eval_enabled is False or llm is None.
        """
        if not self._config.quality_eval_enabled or llm is None:
            return

        self._worker = QualityWorker(
            staging_store=self.staging,
            experience_cache=self.cache,
            experience_store=self.store,
            evaluator=QualityEvaluator(
                min_score=self._config.quality_eval_min_score,
            ),
            poll_interval=self._config.quality_eval_poll_interval,
            max_retries=self._config.quality_eval_max_retries,
        )
        self._task = asyncio.create_task(self._worker.run(llm))
        logger.info("Quality evaluation worker started")

    async def stop(self) -> None:
        """Graceful shutdown with 5s timeout."""
        if self._worker:
            self._worker.stop()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
            self._task = None
            self._worker = None
            logger.info("Quality evaluation worker stopped")

    @property
    def is_running(self) -> bool:
        """Whether the background worker is currently running."""
        return self._task is not None and not self._task.done()

    @property
    def worker_stats(self) -> dict[str, int]:
        """Return worker statistics (promoted/rejected/errors)."""
        if self._worker is None:
            return {"promoted": 0, "rejected": 0, "errors": 0}
        return {
            "promoted": self._worker.promoted,
            "rejected": self._worker.rejected,
            "errors": self._worker.errors,
        }
