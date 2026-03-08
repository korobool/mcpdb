"""Phase 1: Agentic Query Battery — runs queries across all source types with structured logging."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from mcpdb.agent.callbacks import CallbackManager
from mcpdb.agent.graph import run_agent
from mcpdb.config import load_config
from mcpdb.experience.service import ExperienceService
from mcpdb.llm.factory import create_provider
from mcpdb.sources.registry import SourceRegistry


# --- Source configuration ---

SOURCE_CONFIGS = {
    "bgins": {
        "type": "database",
        "connection": "mysql+pymysql://dbtalk:dbtalk@localhost:3306/bgins",
    },
    "portfolio_analysis": {
        "type": "database",
        "connection": "postgresql://readonly:uPxAP3mQ3N74@34.147.20.48/portfolio_analysis?sslmode=require",
    },
    "qala_mtpl": {
        "type": "csv",
        "path": os.path.expanduser("~/Downloads/Qala-MTPL-V4.csv"),
    },
    "contracts_claims": {
        "type": "csv",
        "path": os.path.expanduser("~/Downloads/CONTRACTS2023_Claim_.csv"),
    },
    "paid": {
        "type": "excel",
        "path": os.path.expanduser("~/Downloads/Telegram Desktop/Paid.xlsx"),
    },
    "reserved": {
        "type": "excel",
        "path": os.path.expanduser("~/Downloads/Telegram Desktop/Reserved.xlsx"),
    },
}


@dataclass
class QueryResult:
    """Result of a single query execution."""
    id: str
    question: str
    source: str
    expected_mode: str
    category: str
    status: str = "pending"  # pending, pass, fail, error, timeout
    actual_mode: str = ""
    response: str = ""
    error: str = ""
    error_type: str = ""
    elapsed_s: float = 0.0
    step_count: int = 0
    debug_count: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Truncate large fields for summary
        d["response"] = d["response"][:500] if d["response"] else ""
        d["events"] = []  # Don't include events in summary
        return d


class EventCollector:
    """Collects agent events for logging."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.mode = ""
        self.step_count = 0
        self.debug_count = 0

    def on_event(self, event: Any) -> None:
        self.events.append({
            "type": event.type,
            "data": event.data,
            "timestamp": event.timestamp,
        })
        if event.type == "classify/complete":
            self.mode = event.data.get("mode", "")
        elif event.type == "step/complete":
            self.step_count += 1
        elif event.type == "debug/start":
            self.debug_count += 1


def create_source(source_name: str) -> Any:
    """Create and return a data source."""
    cfg = SOURCE_CONFIGS[source_name]

    if cfg["type"] == "database":
        from mcpdb.sources.database.source import DatabaseSource
        return DatabaseSource(cfg["connection"])
    elif cfg["type"] == "csv":
        from mcpdb.sources.csv.source import CsvSource
        return CsvSource([cfg["path"]], display_name=source_name)
    elif cfg["type"] == "excel":
        from mcpdb.sources.excel.source import ExcelSource
        return ExcelSource(cfg["path"], display_name=source_name)
    else:
        raise ValueError(f"Unknown source type: {cfg['type']}")


async def run_single_query(
    query: dict[str, Any],
    llm: Any,
    config: Any,
    timeout_s: int = 300,
) -> QueryResult:
    """Run a single query and return the result."""
    result = QueryResult(
        id=query["id"],
        question=query["question"],
        source=query["source"],
        expected_mode=query.get("mode", ""),
        category=query.get("category", ""),
        timestamp=datetime.now().isoformat(),
    )

    registry = SourceRegistry()
    collector = EventCollector()
    callbacks = CallbackManager()
    callbacks.add_listener(collector.on_event)

    try:
        source = create_source(query["source"])
        registry.add_source(source)
    except Exception as e:
        result.status = "error"
        result.error = f"Source creation failed: {e}"
        result.error_type = "source_error"
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

        result.elapsed_s = time.time() - start
        result.actual_mode = state.get("query_mode", "")
        result.response = state.get("response") or ""
        result.step_count = collector.step_count
        result.debug_count = collector.debug_count
        result.events = collector.events

        # Determine pass/fail
        if result.response and len(result.response.strip()) > 10:
            result.status = "pass"
        else:
            result.status = "fail"
            result.error = "Empty or trivial response"
            result.error_type = "empty_response"

    except asyncio.TimeoutError:
        result.elapsed_s = time.time() - start
        result.status = "timeout"
        result.error = f"Query timed out after {timeout_s}s"
        result.error_type = "timeout"
    except Exception as e:
        result.elapsed_s = time.time() - start
        result.status = "error"
        result.error = str(e)
        result.error_type = type(e).__name__
        result.events = collector.events
    finally:
        try:
            registry.close_all()
        except Exception:
            pass

    result.actual_mode = collector.mode or result.actual_mode
    return result


async def run_battery(
    query_file: str,
    source_filter: str | None = None,
    category_filter: str | None = None,
    limit: int | None = None,
    timeout_s: int = 300,
) -> list[QueryResult]:
    """Run a battery of queries from a JSON file."""
    config = load_config()
    llm_cfg = config.llm.reasoning
    llm = create_provider(llm_cfg.provider, llm_cfg.model, llm_cfg.api_key)

    with open(query_file) as f:
        queries = json.load(f)

    # Apply filters
    if source_filter:
        queries = [q for q in queries if q["source"] == source_filter]
    if category_filter:
        queries = [q for q in queries if q["category"] == category_filter]
    if limit:
        queries = queries[:limit]

    print(f"\n{'='*60}")
    print(f"Query Battery: {Path(query_file).stem}")
    print(f"Queries: {len(queries)}")
    if source_filter:
        print(f"Source filter: {source_filter}")
    if category_filter:
        print(f"Category filter: {category_filter}")
    print(f"{'='*60}\n")

    results: list[QueryResult] = []
    passed = 0
    failed = 0
    errors = 0
    timeouts = 0

    for i, query in enumerate(queries, 1):
        qid = query["id"]
        question = query["question"][:60]
        source = query["source"]

        print(f"[{i}/{len(queries)}] {qid} ({source}) {question}...", end=" ", flush=True)

        result = await run_single_query(query, llm, config, timeout_s=timeout_s)
        results.append(result)

        # Print status
        if result.status == "pass":
            passed += 1
            print(f"✓ {result.actual_mode} {result.elapsed_s:.1f}s ({result.step_count} steps)")
        elif result.status == "fail":
            failed += 1
            print(f"✗ FAIL: {result.error[:50]}")
        elif result.status == "timeout":
            timeouts += 1
            print(f"⏱ TIMEOUT ({timeout_s}s)")
        else:
            errors += 1
            print(f"✗ ERROR: {result.error[:50]}")

    # Summary
    total = len(results)
    print(f"\n{'='*60}")
    print(f"Results: {passed}/{total} passed ({100*passed/total:.1f}%)")
    print(f"  Pass: {passed} | Fail: {failed} | Error: {errors} | Timeout: {timeouts}")
    print(f"{'='*60}\n")

    return results


def save_results(results: list[QueryResult], output_dir: str, label: str) -> str:
    """Save results to JSONL file."""
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(output_dir, f"{label}_{timestamp}.jsonl")

    with open(filepath, "w") as f:
        for result in results:
            f.write(json.dumps(result.to_dict(), default=str) + "\n")

    print(f"Results saved to: {filepath}")
    return filepath


def generate_report(all_results: dict[str, list[QueryResult]], output_path: str) -> None:
    """Generate a markdown report from all battery results."""
    lines = [
        "# Phase 1: Query Battery Report",
        f"\nGenerated: {datetime.now().isoformat()}",
        "",
    ]

    total_pass = 0
    total_queries = 0

    for source_type, results in all_results.items():
        passed = sum(1 for r in results if r.status == "pass")
        total = len(results)
        total_pass += passed
        total_queries += total
        pct = 100 * passed / total if total else 0

        lines.append(f"## {source_type}")
        lines.append(f"\n**Pass rate: {passed}/{total} ({pct:.1f}%)**\n")

        # Category breakdown
        categories: dict[str, list[QueryResult]] = {}
        for r in results:
            categories.setdefault(r.category, []).append(r)

        lines.append("| Category | Pass | Fail | Error | Timeout |")
        lines.append("|----------|------|------|-------|---------|")
        for cat, cat_results in sorted(categories.items()):
            p = sum(1 for r in cat_results if r.status == "pass")
            f = sum(1 for r in cat_results if r.status == "fail")
            e = sum(1 for r in cat_results if r.status == "error")
            t = sum(1 for r in cat_results if r.status == "timeout")
            lines.append(f"| {cat} | {p} | {f} | {e} | {t} |")

        # Failures detail
        failures = [r for r in results if r.status != "pass"]
        if failures:
            lines.append("\n### Failures\n")
            for r in failures:
                lines.append(f"- **{r.id}**: [{r.status}] {r.question[:60]}")
                lines.append(f"  - Error: {r.error[:100]}")
                lines.append(f"  - Mode: expected={r.expected_mode}, actual={r.actual_mode}")

        # Timing stats
        times = [r.elapsed_s for r in results if r.elapsed_s > 0]
        if times:
            avg_time = sum(times) / len(times)
            max_time = max(times)
            lines.append(f"\n**Timing:** avg={avg_time:.1f}s, max={max_time:.1f}s\n")

        lines.append("")

    # Overall summary
    overall_pct = 100 * total_pass / total_queries if total_queries else 0
    lines.insert(2, f"\n**Overall: {total_pass}/{total_queries} ({overall_pct:.1f}%)**\n")

    report = "\n".join(lines)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(report)
    print(f"Report saved to: {output_path}")


async def main():
    """Run all query batteries."""
    import argparse

    parser = argparse.ArgumentParser(description="Run query battery tests")
    parser.add_argument("--source", help="Filter by source name")
    parser.add_argument("--category", help="Filter by category")
    parser.add_argument("--limit", type=int, help="Limit number of queries")
    parser.add_argument("--timeout", type=int, default=300, help="Timeout per query (seconds)")
    parser.add_argument("--battery", choices=["db", "csv", "xlsx", "all"], default="all",
                        help="Which battery to run")
    args = parser.parse_args()

    base_dir = Path(__file__).parent
    query_dir = base_dir / "queries"
    results_dir = base_dir / "results"
    report_dir = base_dir / "reports"

    all_results: dict[str, list[QueryResult]] = {}

    batteries = {
        "db": ("db_queries.json", "db"),
        "csv": ("csv_queries.json", "csv"),
        "xlsx": ("xlsx_queries.json", "xlsx"),
    }

    if args.battery == "all":
        to_run = list(batteries.items())
    else:
        to_run = [(args.battery, batteries[args.battery])]

    for label, (query_file, result_subdir) in to_run:
        filepath = query_dir / query_file
        if not filepath.exists():
            print(f"Skipping {label}: {filepath} not found")
            continue

        results = await run_battery(
            str(filepath),
            source_filter=args.source,
            category_filter=args.category,
            limit=args.limit,
            timeout_s=args.timeout,
        )

        save_results(results, str(results_dir / result_subdir), label)
        all_results[label] = results

    if all_results:
        generate_report(all_results, str(report_dir / "phase1_report.md"))


if __name__ == "__main__":
    asyncio.run(main())
