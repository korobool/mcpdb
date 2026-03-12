"""Background quality worker — async evaluation of staged results.

Runs as a long-lived asyncio coroutine (in Playground's FastAPI lifespan).
Polls the staging store every 30 seconds for unevaluated records and
processes them one at a time to avoid LLM quota exhaustion.

Lifecycle:
    worker = QualityWorker(staging, cache, store)
    task = asyncio.create_task(worker.run(llm))
    ...
    worker.stop()           # signal graceful shutdown
    await task              # wait for current eval to finish

On promote (score >= threshold):
    StagedRecord → SuccessRecord → ExperienceStore + ExperienceCache memory

On reject (score < threshold):
    StagedRecord → FailureRecord (error_type="quality_rejected") with
    quality feedback in error_message. This feeds into the anti-pattern
    tracker so future planning can learn what NOT to do.

On LLM failure:
    Retries up to 3 times with exponential backoff. After exhausting
    retries, records FailureRecord with error_type="quality_eval_failed".
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from mcpdb.experience.cache import ExperienceCache
from mcpdb.experience.evaluator import QualityEvaluator
from mcpdb.experience.records import FailureRecord, StagedRecord
from mcpdb.experience.staging import StagingStore
from mcpdb.experience.store import ExperienceStore

logger = logging.getLogger("mcpdb.experience.worker")


class QualityWorker:
    """Background worker that evaluates staged records and promotes/rejects them.

    Runs as a long-lived async coroutine. Polls the staging store for
    unevaluated records, evaluates them via LLM, then either promotes
    to the experience cache or records as anti-pattern.

    Supports pause/resume to yield LLM access to user queries.
    """

    def __init__(
        self,
        staging_store: StagingStore,
        experience_cache: ExperienceCache,
        experience_store: ExperienceStore,
        evaluator: QualityEvaluator | None = None,
        poll_interval: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        self._staging = staging_store
        self._cache = experience_cache
        self._store = experience_store
        self._evaluator = evaluator or QualityEvaluator()
        self._poll_interval = poll_interval
        self._max_retries = max_retries
        self._stop_event = asyncio.Event()
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # starts unpaused

        # Stats
        self.promoted = 0
        self.rejected = 0
        self.errors = 0

    def pause(self) -> None:
        """Pause the worker — yields LLM access to user queries.

        The worker will finish its current evaluation (if any), then wait
        until resume() is called before starting the next one.
        """
        if self._pause_event.is_set():
            logger.info("Quality worker paused (yielding LLM to user query)")
            self._pause_event.clear()

    def resume(self) -> None:
        """Resume the worker after a pause."""
        if not self._pause_event.is_set():
            logger.info("Quality worker resumed")
            self._pause_event.set()

    @property
    def is_paused(self) -> bool:
        return not self._pause_event.is_set()

    async def run(self, llm: Any) -> None:
        """Main worker loop — polls staging store and evaluates records.

        Runs until stop() is called.
        """
        logger.info("Quality worker started (poll_interval=%.0fs)", self._poll_interval)

        while not self._stop_event.is_set():
            # Wait if paused (check stop every second to stay responsive)
            while not self._pause_event.is_set() and not self._stop_event.is_set():
                try:
                    await asyncio.wait_for(self._pause_event.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    pass

            if self._stop_event.is_set():
                break

            try:
                await self._process_pending(llm)
            except Exception:
                logger.exception("Error in quality worker loop")

            # Wait for poll interval or stop signal
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._poll_interval,
                )
                break  # stop was signalled
            except asyncio.TimeoutError:
                pass  # poll interval elapsed, continue

        logger.info(
            "Quality worker stopped (promoted=%d, rejected=%d, errors=%d)",
            self.promoted, self.rejected, self.errors,
        )

    def stop(self) -> None:
        """Signal the worker to stop after current evaluation completes."""
        self._stop_event.set()
        self._pause_event.set()  # unblock if paused so stop can proceed

    async def _process_pending(self, llm: Any) -> None:
        """Process all pending staged records, one at a time."""
        pending = self._staging.get_all_pending()
        if not pending:
            return

        logger.debug("Processing %d pending staged records", len(pending))

        for record in pending:
            if self._stop_event.is_set():
                break
            # Yield to user queries if paused
            if not self._pause_event.is_set():
                logger.debug("Worker paused mid-batch, waiting for resume")
                await self._pause_event.wait()
                if self._stop_event.is_set():
                    break
            await self._evaluate_record(record, llm)

    async def _evaluate_record(self, record: StagedRecord, llm: Any) -> None:
        """Evaluate a single staged record and promote or reject it."""
        fp = record.source_fingerprint
        ih = record.intent_hash

        for attempt in range(1, self._max_retries + 1):
            try:
                result = await self._evaluator.evaluate(record, llm)
                break
            except Exception as e:
                if attempt == self._max_retries:
                    logger.warning(
                        "Evaluation failed after %d attempts for %s: %s",
                        self._max_retries, ih, e,
                    )
                    # Mark evaluated and record as rejected
                    self._staging.mark_evaluated(fp, ih)
                    self._staging.remove(fp, ih)
                    self._store.store_failure(FailureRecord(
                        question=record.question,
                        source_fingerprint=fp,
                        error_type="quality_eval_failed",
                        error_message=f"LLM evaluation failed: {e}",
                        failed_code="",
                    ))
                    self.errors += 1
                    return
                await asyncio.sleep(1.0 * attempt)  # backoff

        if result.verdict == "promote":
            # Promote to experience cache
            success = record.to_success_record()
            self._store.store_success(success)
            # Also put into in-memory cache
            self._cache._memory[ih] = success
            if success.semantic_hash:
                self._cache._semantic_index[success.semantic_hash] = ih
            self._cache._evict_memory_if_needed()

            self._staging.remove(fp, ih)
            self.promoted += 1
            logger.info(
                "Promoted record %s (score=%d): %s",
                ih, result.score, record.question[:60],
            )
        else:
            # Reject — store as anti-pattern with quality feedback
            self._staging.remove(fp, ih)
            self._store.store_failure(FailureRecord(
                question=record.question,
                source_fingerprint=fp,
                error_type="quality_rejected",
                error_message=(
                    f"Score {result.score}/10 "
                    f"(completeness={result.completeness}, accuracy={result.accuracy}, "
                    f"relevance={result.relevance}, clarity={result.clarity}). "
                    f"Issues: {'; '.join(result.issues) if result.issues else 'none'}"
                ),
                failed_code=record.response[:500],
            ))
            self.rejected += 1
            logger.info(
                "Rejected record %s (score=%d): %s",
                ih, result.score, record.question[:60],
            )
