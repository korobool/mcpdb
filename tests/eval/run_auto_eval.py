#!/usr/bin/env python3
"""Autonomous evaluation runner with observer monitoring.

Runs test questions against real data sources, collects observer reports,
identifies issues, and outputs a comprehensive analysis.

Usage:
    # Run all questions (DB + CSV)
    python -m tests.eval.run_auto_eval --all

    # Run only DB questions
    python -m tests.eval.run_auto_eval --db

    # Run only CSV questions (Qala)
    python -m tests.eval.run_auto_eval --qala

    # Run only CSV questions (Lithuania)
    python -m tests.eval.run_auto_eval --lt

    # Run specific question IDs
    python -m tests.eval.run_auto_eval --ids db01 db05 qa01

    # Run only quick-tier questions
    python -m tests.eval.run_auto_eval --quick

    # Run with specific mode override
    python -m tests.eval.run_auto_eval --mode simple --ids db01 db02

    # Dry run (list questions without executing)
    python -m tests.eval.run_auto_eval --dry-run --all
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Add project root to path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from mcpdb.agent.callbacks import CallbackManager
from mcpdb.agent.cancellation import CancellationToken
from mcpdb.agent.graph import run_agent
from mcpdb.agent.observer import AsyncReasoningObserver, ObserverReport
from mcpdb.llm.factory import create_provider
from mcpdb.sources.registry import SourceRegistry
from tests.eval.questions_auto import (
    ALL_QUESTIONS,
    DB_QUESTIONS,
    QALA_QUESTIONS,
    LT_QUESTIONS,
    QUICK_ONLY,
    SIMPLE_ONLY,
    COMPLEX_ONLY,
    EvalQuestion,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("auto_eval")


# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------

@dataclass
class QuestionResult:
    """Result of a single question evaluation."""
    question_id: str
    question: str
    source: str
    expected_mode: str
    actual_mode: str
    max_time_s: int
    actual_time_s: float
    status: str  # pass, fail, error, timeout, hang
    response_preview: str
    error_message: str
    observer_anomalies: int
    observer_summary: str
    timing_ok: bool
    mode_ok: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "question": self.question,
            "source": self.source,
            "expected_mode": self.expected_mode,
            "actual_mode": self.actual_mode,
            "max_time_s": self.max_time_s,
            "actual_time_s": round(self.actual_time_s, 2),
            "status": self.status,
            "response_preview": self.response_preview[:500],
            "error_message": self.error_message,
            "observer_anomalies": self.observer_anomalies,
            "observer_summary": self.observer_summary,
            "timing_ok": self.timing_ok,
            "mode_ok": self.mode_ok,
        }


@dataclass
class EvalSummary:
    """Summary of the full evaluation run."""
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    timeouts: int = 0
    hangs: int = 0
    timing_violations: int = 0
    mode_mismatches: int = 0
    total_time_s: float = 0.0
    total_anomalies: int = 0
    results: list[QuestionResult] = field(default_factory=list)

    def print_report(self) -> None:
        print("\n" + "=" * 80)
        print("AUTONOMOUS EVAL SUMMARY")
        print("=" * 80)
        print(f"Total: {self.total} | Pass: {self.passed} | Fail: {self.failed} | "
              f"Error: {self.errors} | Timeout: {self.timeouts} | Hang: {self.hangs}")
        print(f"Time: {self.total_time_s:.1f}s total | "
              f"Timing violations: {self.timing_violations} | "
              f"Mode mismatches: {self.mode_mismatches}")
        print(f"Observer anomalies: {self.total_anomalies}")
        print()

        # Issues table
        issues = [r for r in self.results if r.status != "pass"]
        if issues:
            print("ISSUES:")
            print("-" * 80)
            for r in issues:
                print(f"  [{r.status.upper():7s}] {r.question_id}: {r.question[:60]}")
                if r.error_message:
                    print(f"           Error: {r.error_message[:100]}")
                if r.observer_anomalies:
                    print(f"           Observer: {r.observer_summary[:100]}")
                print()

        # Timing violations
        timing_issues = [r for r in self.results if not r.timing_ok]
        if timing_issues:
            print("TIMING VIOLATIONS:")
            print("-" * 80)
            for r in timing_issues:
                ratio = r.actual_time_s / r.max_time_s if r.max_time_s > 0 else 0
                print(f"  {r.question_id}: {r.actual_time_s:.1f}s / {r.max_time_s}s "
                      f"({ratio:.1f}x) [{r.actual_mode}]")
            print()

        # Mode mismatches
        mode_issues = [r for r in self.results if not r.mode_ok]
        if mode_issues:
            print("MODE MISMATCHES:")
            print("-" * 80)
            for r in mode_issues:
                print(f"  {r.question_id}: expected={r.expected_mode}, actual={r.actual_mode}")
            print()

    def to_json(self) -> str:
        return json.dumps({
            "summary": {
                "total": self.total,
                "passed": self.passed,
                "failed": self.failed,
                "errors": self.errors,
                "timeouts": self.timeouts,
                "hangs": self.hangs,
                "timing_violations": self.timing_violations,
                "mode_mismatches": self.mode_mismatches,
                "total_time_s": round(self.total_time_s, 2),
                "total_anomalies": self.total_anomalies,
            },
            "results": [r.to_dict() for r in self.results],
        }, indent=2)


# ---------------------------------------------------------------------------
# Source setup
# ---------------------------------------------------------------------------

def setup_db_source(registry: SourceRegistry) -> str:
    """Connect bgins MySQL database. Returns source_id."""
    conn_str = os.environ.get(
        "MCPDB_DATABASE_URL",
        "mysql+pymysql://dbtalk:dbtalk@localhost:3306/bgins",
    )
    from mcpdb.sources.database.source import DatabaseSource
    source = DatabaseSource(conn_str, display_name="bgins")
    registry.add_source(source)
    return source.get_metadata().source_id


def setup_csv_source(registry: SourceRegistry, csv_path: str, name: str) -> str:
    """Load a CSV file. Returns source_id."""
    from mcpdb.sources.csv.source import CsvSource
    source = CsvSource(csv_path, display_name=name)
    registry.add_source(source)
    return source.get_metadata().source_id


# ---------------------------------------------------------------------------
# Question runner
# ---------------------------------------------------------------------------

async def run_question(
    q: EvalQuestion,
    registry: SourceRegistry,
    llm: Any,
    mode_override: str | None = None,
    timeout_s: int | None = None,
) -> QuestionResult:
    """Run a single question and return the result."""
    timeout = timeout_s or (q.max_time_s * 3)  # 3x max time as hard timeout
    start = time.time()

    callbacks = CallbackManager()
    cancel_token = CancellationToken()

    actual_mode = mode_override or "auto"
    status = "pass"
    response_preview = ""
    error_message = ""
    observer_report: ObserverReport | None = None

    try:
        state = await asyncio.wait_for(
            run_agent(
                question=q.question,
                registry=registry,
                llm=llm,
                callbacks=callbacks,
                mode_override=mode_override,
                no_cache=True,
                cancellation_token=cancel_token,
                enable_observer=True,
            ),
            timeout=timeout,
        )

        actual_mode = state.get("query_mode", "unknown")
        response = state.get("response", "")
        response_preview = response[:500] if response else ""

        # Check for empty/error response
        if not response or len(response.strip()) < 10:
            status = "fail"
            error_message = "Empty or too-short response"
        elif any(phrase in response.lower() for phrase in [
            "could not", "unable to", "error:", "failed to",
        ]):
            status = "fail"
            error_message = "Response indicates failure"

    except asyncio.TimeoutError:
        status = "timeout"
        error_message = f"Timed out after {timeout}s"
    except Exception as e:
        status = "error"
        error_message = f"{type(e).__name__}: {str(e)[:200]}"

    elapsed = time.time() - start
    timing_ok = elapsed <= q.max_time_s

    # Mode hierarchy check (actual should be <= expected complexity)
    mode_order = {"quick": 0, "simple": 1, "optimization_required": 2, "extended": 3, "deep": 4}
    expected_rank = mode_order.get(q.expected_mode, 1)
    actual_rank = mode_order.get(actual_mode, 1)
    # Allow one step higher or lower
    mode_ok = abs(actual_rank - expected_rank) <= 1

    # Get observer data from callback events
    observer_events = [e for e in callbacks.get_events() if e.type.startswith("observer/")]
    anomaly_count = sum(1 for e in observer_events if e.type == "observer/warning")
    report_events = [e for e in observer_events if e.type == "observer/report"]
    observer_summary = ""
    if report_events:
        observer_summary = report_events[-1].data.get("summary", "")
        anomaly_count = report_events[-1].data.get("anomaly_count", anomaly_count)

    return QuestionResult(
        question_id=q.id,
        question=q.question,
        source=q.source,
        expected_mode=q.expected_mode,
        actual_mode=actual_mode,
        max_time_s=q.max_time_s,
        actual_time_s=elapsed,
        status=status,
        response_preview=response_preview,
        error_message=error_message,
        observer_anomalies=anomaly_count,
        observer_summary=observer_summary,
        timing_ok=timing_ok,
        mode_ok=mode_ok,
    )


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

async def run_eval(
    questions: list[EvalQuestion],
    mode_override: str | None = None,
    timeout_s: int | None = None,
    output_file: str | None = None,
) -> EvalSummary:
    """Run the full evaluation suite."""
    summary = EvalSummary()

    # Group questions by source
    by_source: dict[str, list[EvalQuestion]] = {}
    for q in questions:
        by_source.setdefault(q.source, []).append(q)

    # Create LLM provider (default: gemini)
    provider_name = os.environ.get("MCPDB_LLM_PROVIDER", "gemini")
    model = os.environ.get("MCPDB_LLM_MODEL", "")
    llm = create_provider(provider_name, model=model)
    logger.info("LLM provider: %s", type(llm).__name__)

    for source_name, source_questions in by_source.items():
        # Setup registry for this source
        registry = SourceRegistry()

        if source_name == "bgins":
            try:
                sid = setup_db_source(registry)
                logger.info("Connected to bgins database (source: %s)", sid)
            except Exception as e:
                logger.error("Failed to connect to bgins: %s", e)
                for q in source_questions:
                    summary.results.append(QuestionResult(
                        question_id=q.id, question=q.question, source=q.source,
                        expected_mode=q.expected_mode, actual_mode="n/a",
                        max_time_s=q.max_time_s, actual_time_s=0,
                        status="error", response_preview="",
                        error_message=f"Source setup failed: {e}",
                        observer_anomalies=0, observer_summary="",
                        timing_ok=False, mode_ok=False,
                    ))
                    summary.errors += 1
                    summary.total += 1
                continue

        elif source_name == "qala":
            csv_path = os.path.expanduser("~/Downloads/Qala-MTPL-V4.csv")
            if not Path(csv_path).exists():
                logger.error("Qala CSV not found: %s", csv_path)
                continue
            try:
                sid = setup_csv_source(registry, csv_path, "Qala-MTPL")
                logger.info("Loaded Qala CSV (source: %s)", sid)
            except Exception as e:
                logger.error("Failed to load Qala CSV: %s", e)
                continue

        elif source_name == "lithuania":
            csv_path = os.path.expanduser("~/Downloads/Lithuania-MTPL-16042025-score-19042025-v5.csv")
            if not Path(csv_path).exists():
                logger.error("Lithuania CSV not found: %s", csv_path)
                continue
            try:
                sid = setup_csv_source(registry, csv_path, "Lithuania-MTPL")
                logger.info("Loaded Lithuania CSV (source: %s)", sid)
            except Exception as e:
                logger.error("Failed to load Lithuania CSV: %s", e)
                continue

        # Run questions for this source
        for i, q in enumerate(source_questions, 1):
            logger.info(
                "[%d/%d] %s: %s (expected: %s, max: %ds)",
                i, len(source_questions), q.id, q.question[:60],
                q.expected_mode, q.max_time_s,
            )

            result = await run_question(
                q, registry, llm,
                mode_override=mode_override,
                timeout_s=timeout_s,
            )

            summary.results.append(result)
            summary.total += 1

            if result.status == "pass":
                summary.passed += 1
            elif result.status == "fail":
                summary.failed += 1
            elif result.status == "error":
                summary.errors += 1
            elif result.status == "timeout":
                summary.timeouts += 1
            elif result.status == "hang":
                summary.hangs += 1

            if not result.timing_ok:
                summary.timing_violations += 1
            if not result.mode_ok:
                summary.mode_mismatches += 1
            summary.total_anomalies += result.observer_anomalies
            summary.total_time_s += result.actual_time_s

            # Real-time status
            icon = {"pass": "+", "fail": "x", "error": "!", "timeout": "T", "hang": "H"}.get(result.status, "?")
            timing_flag = "" if result.timing_ok else f" [SLOW {result.actual_time_s:.0f}s/{q.max_time_s}s]"
            logger.info(
                "  [%s] %s: %.1fs%s",
                icon, q.id, result.actual_time_s, timing_flag,
            )

        # Cleanup source
        try:
            for meta in registry.list_sources():
                registry.remove_source(meta.source_id)
        except Exception:
            pass

    # Output report
    summary.print_report()

    if output_file:
        Path(output_file).write_text(summary.to_json())
        logger.info("Results written to %s", output_file)

    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Autonomous eval with observer monitoring")
    parser.add_argument("--all", action="store_true", help="Run all questions")
    parser.add_argument("--db", action="store_true", help="Run DB questions only")
    parser.add_argument("--qala", action="store_true", help="Run Qala CSV questions only")
    parser.add_argument("--lt", action="store_true", help="Run Lithuania CSV questions only")
    parser.add_argument("--quick", action="store_true", help="Run quick-tier only")
    parser.add_argument("--simple", action="store_true", help="Run simple-tier only")
    parser.add_argument("--complex", action="store_true", help="Run complex-tier only")
    parser.add_argument("--ids", nargs="+", help="Run specific question IDs")
    parser.add_argument("--mode", help="Override mode for all questions")
    parser.add_argument("--timeout", type=int, help="Override timeout in seconds")
    parser.add_argument("--output", "-o", help="Output JSON file path")
    parser.add_argument("--dry-run", action="store_true", help="List questions without running")

    args = parser.parse_args()

    # Select questions
    questions: list[EvalQuestion] = []

    if args.ids:
        id_set = set(args.ids)
        questions = [q for q in ALL_QUESTIONS if q.id in id_set]
    elif args.quick:
        questions = QUICK_ONLY
    elif args.simple:
        questions = SIMPLE_ONLY
    elif args.complex:
        questions = COMPLEX_ONLY
    elif args.db:
        questions = DB_QUESTIONS
    elif args.qala:
        questions = QALA_QUESTIONS
    elif args.lt:
        questions = LT_QUESTIONS
    elif args.all:
        questions = ALL_QUESTIONS
    else:
        parser.print_help()
        print("\nSpecify at least one question set (--all, --db, --qala, --lt, --quick, etc.)")
        sys.exit(1)

    if not questions:
        print("No questions matched the selection criteria.")
        sys.exit(1)

    print(f"Selected {len(questions)} questions:")
    for q in questions:
        print(f"  {q.id}: [{q.expected_mode:20s}] {q.question[:60]}")

    if args.dry_run:
        print("\n(dry run — not executing)")
        sys.exit(0)

    print()

    output = args.output or f"tests/eval/auto_eval_results_{int(time.time())}.json"

    summary = asyncio.run(run_eval(
        questions=questions,
        mode_override=args.mode,
        timeout_s=args.timeout,
        output_file=output,
    ))

    sys.exit(0 if summary.failed + summary.errors + summary.timeouts == 0 else 1)


if __name__ == "__main__":
    main()
