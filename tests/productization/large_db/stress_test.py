"""Phase 4: Stress test runner for the large SQLite database."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from mcpdb.agent.callbacks import CallbackManager
from mcpdb.agent.graph import run_agent
from mcpdb.config import load_config
from mcpdb.llm.factory import create_provider
from mcpdb.sources.database.source import DatabaseSource
from mcpdb.sources.registry import SourceRegistry

DB_PATH = Path(__file__).parent / "stress_test.db"
QUERIES_PATH = Path(__file__).parent / "stress_queries.json"
RESULTS_DIR = Path(__file__).parent.parent / "results" / "stress"
REPORT_PATH = Path(__file__).parent.parent / "reports" / "phase4_report.md"


class StressEventCollector:
    """Collects events with performance focus."""

    def __init__(self) -> None:
        self.mode = ""
        self.step_count = 0
        self.debug_count = 0
        self.sql_times: list[int] = []
        self.warnings: list[str] = []
        self.events: list[dict[str, Any]] = []

    def on_event(self, event: Any) -> None:
        self.events.append({"type": event.type, "ts": event.timestamp})

        if event.type == "classify/complete":
            self.mode = event.data.get("mode", "")
        elif event.type == "step/complete":
            self.step_count += 1
            self.sql_times.append(event.data.get("time_ms", 0))
        elif event.type == "debug/start":
            self.debug_count += 1
        elif event.type == "observer/warning":
            self.warnings.append(event.data.get("message", ""))


async def run_stress_query(
    query: dict[str, Any],
    llm: Any,
    timeout_s: int = 600,
) -> dict[str, Any]:
    """Run a single stress test query."""
    result = {
        "id": query["id"],
        "question": query["question"],
        "category": query["category"],
        "expected_behavior": query.get("expected_behavior", ""),
        "status": "pending",
        "mode": "",
        "elapsed_s": 0.0,
        "step_count": 0,
        "debug_count": 0,
        "max_step_ms": 0,
        "total_step_ms": 0,
        "response_len": 0,
        "warnings": [],
        "error": "",
        "timestamp": datetime.now().isoformat(),
    }

    conn_str = f"sqlite:///{DB_PATH}"
    registry = SourceRegistry()
    collector = StressEventCollector()
    callbacks = CallbackManager()
    callbacks.add_listener(collector.on_event)

    try:
        source = DatabaseSource(conn_str)
        registry.add_source(source)
    except Exception as e:
        result["status"] = "error"
        result["error"] = f"Source error: {e}"
        return result

    start = time.time()
    try:
        state = await asyncio.wait_for(
            run_agent(
                query["question"],
                registry,
                llm,
                callbacks,
                no_cache=True,
            ),
            timeout=timeout_s,
        )

        result["elapsed_s"] = time.time() - start
        result["mode"] = collector.mode
        result["step_count"] = collector.step_count
        result["debug_count"] = collector.debug_count
        result["max_step_ms"] = max(collector.sql_times) if collector.sql_times else 0
        result["total_step_ms"] = sum(collector.sql_times)
        result["warnings"] = collector.warnings
        response = state.get("response") or ""
        result["response_len"] = len(response)

        if response and len(response.strip()) > 10:
            result["status"] = "pass"
        else:
            result["status"] = "fail"
            result["error"] = "Empty or trivial response"

    except asyncio.TimeoutError:
        result["elapsed_s"] = time.time() - start
        result["status"] = "timeout"
        result["error"] = f"Timed out after {timeout_s}s"
    except Exception as e:
        result["elapsed_s"] = time.time() - start
        result["status"] = "error"
        result["error"] = str(e)
    finally:
        try:
            registry.close_all()
        except Exception:
            pass

    return result


def generate_report(results: list[dict[str, Any]]) -> None:
    """Generate Phase 4 report."""
    lines = [
        "# Phase 4: Large Database Stress Test Report",
        f"\nGenerated: {datetime.now().isoformat()}",
        f"\nDatabase: {DB_PATH} ({DB_PATH.stat().st_size / 1024 / 1024:.1f} MB)",
        "\n## Summary\n",
    ]

    total = len(results)
    passed = sum(1 for r in results if r["status"] == "pass")
    failed = sum(1 for r in results if r["status"] == "fail")
    errors = sum(1 for r in results if r["status"] == "error")
    timeouts = sum(1 for r in results if r["status"] == "timeout")
    pct = 100 * passed / total if total else 0

    lines.append(f"**Overall: {passed}/{total} ({pct:.1f}%)**\n")
    lines.append(f"- Pass: {passed}")
    lines.append(f"- Fail: {failed}")
    lines.append(f"- Error: {errors}")
    lines.append(f"- Timeout: {timeouts}")

    # Timing stats
    times = [r["elapsed_s"] for r in results if r["elapsed_s"] > 0]
    if times:
        avg_t = sum(times) / len(times)
        max_t = max(times)
        total_t = sum(times)
        lines.append(f"\n**Timing:** avg={avg_t:.1f}s, max={max_t:.1f}s, total={total_t:.0f}s")

    # Step timing
    step_times = [r["max_step_ms"] for r in results if r["max_step_ms"] > 0]
    if step_times:
        avg_step = sum(step_times) / len(step_times)
        max_step = max(step_times)
        lines.append(f"**Step timing:** avg_max_step={avg_step:.0f}ms, absolute_max={max_step:.0f}ms")

    # By category
    categories: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        categories.setdefault(r["category"], []).append(r)

    lines.append("\n## By Category\n")
    lines.append("| Category | Pass | Fail | Error | Timeout | Avg Time |")
    lines.append("|----------|------|------|-------|---------|----------|")
    for cat, cat_results in sorted(categories.items()):
        p = sum(1 for r in cat_results if r["status"] == "pass")
        f = sum(1 for r in cat_results if r["status"] == "fail")
        e = sum(1 for r in cat_results if r["status"] == "error")
        t = sum(1 for r in cat_results if r["status"] == "timeout")
        avg = sum(r["elapsed_s"] for r in cat_results) / len(cat_results)
        lines.append(f"| {cat} | {p} | {f} | {e} | {t} | {avg:.1f}s |")

    # Failures detail
    failures = [r for r in results if r["status"] != "pass"]
    if failures:
        lines.append("\n## Failures\n")
        for r in failures:
            lines.append(f"- **{r['id']}** [{r['status']}]: {r['question'][:60]}")
            lines.append(f"  - Error: {r['error'][:100]}")
            lines.append(f"  - Mode: {r['mode']}, Time: {r['elapsed_s']:.1f}s")

    # Performance warnings
    slow = [r for r in results if r["elapsed_s"] > 120]
    if slow:
        lines.append("\n## Slow Queries (>120s)\n")
        for r in slow:
            lines.append(f"- **{r['id']}**: {r['elapsed_s']:.1f}s — {r['question'][:60]}")

    report = "\n".join(lines)
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w") as f:
        f.write(report)
    print(f"Report saved to: {REPORT_PATH}")


async def main():
    """Run the stress test battery."""
    import argparse

    parser = argparse.ArgumentParser(description="Run large DB stress tests")
    parser.add_argument("--limit", type=int, help="Limit number of queries")
    parser.add_argument("--category", help="Filter by category")
    parser.add_argument("--timeout", type=int, default=600, help="Timeout per query (seconds)")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print("Database not found. Run setup_large_db.py first.")
        sys.exit(1)

    with open(QUERIES_PATH) as f:
        queries = json.load(f)

    if args.category:
        queries = [q for q in queries if q["category"] == args.category]
    if args.limit:
        queries = queries[:args.limit]

    config = load_config()
    llm_cfg = config.llm.reasoning
    llm = create_provider(llm_cfg.provider, llm_cfg.model, llm_cfg.api_key)

    print(f"\n{'='*60}")
    print(f"Stress Test: {len(queries)} queries on {DB_PATH.stat().st_size / 1024 / 1024:.1f} MB database")
    print(f"{'='*60}\n")

    results = []
    for i, query in enumerate(queries, 1):
        qid = query["id"]
        question = query["question"][:55]
        print(f"[{i}/{len(queries)}] {qid} {question}...", end=" ", flush=True)

        result = await run_stress_query(query, llm, timeout_s=args.timeout)
        results.append(result)

        if result["status"] == "pass":
            print(f"✓ {result['mode']} {result['elapsed_s']:.1f}s "
                  f"({result['step_count']} steps, max_step={result['max_step_ms']}ms)")
        elif result["status"] == "timeout":
            print(f"⏱ TIMEOUT ({args.timeout}s)")
        else:
            print(f"✗ {result['status'].upper()}: {result['error'][:40]}")

    # Save results
    os.makedirs(RESULTS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_path = RESULTS_DIR / f"stress_{ts}.jsonl"
    with open(results_path, "w") as f:
        for r in results:
            f.write(json.dumps(r, default=str) + "\n")
    print(f"\nResults saved to: {results_path}")

    # Summary
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "pass")
    print(f"\n{'='*60}")
    print(f"Stress Test: {passed}/{total} passed ({100*passed/total:.1f}%)")
    print(f"{'='*60}\n")

    generate_report(results)


if __name__ == "__main__":
    asyncio.run(main())
