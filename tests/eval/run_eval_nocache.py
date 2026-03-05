"""No-cache evaluation harness — runs agent WITHOUT experience cache.

Imports shared questions and scoring from run_eval.py, overrides agent execution
to disable caching, and captures enhanced per-question metrics.

Supports --resume to continue from partial results after crashes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

import sqlalchemy

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mcpdb.agent.graph import run_agent
from mcpdb.agent.callbacks import CallbackManager
from mcpdb.llm.factory import create_provider
from mcpdb.sources.database.source import DatabaseSource
from mcpdb.sources.registry import SourceRegistry

from run_eval import QUESTIONS, compute_ground_truth, evaluate_response

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("eval_nocache")

# Question ID → category mapping
CATEGORY_MAP = {
    **{i: "Counts" for i in range(1, 11)},
    **{i: "Aggregation" for i in range(11, 26)},
    **{i: "Filtering" for i in range(26, 41)},
    **{i: "Top-N" for i in range(41, 56)},
    **{i: "Dates" for i in range(56, 66)},
    **{i: "Joins" for i in range(66, 81)},
    **{i: "Complex" for i in range(81, 91)},
    **{i: "Domain" for i in range(91, 101)},
}

RESULTS_PATH = Path(__file__).parent / "eval_nocache_results.json"


async def run_agent_nocache(question: str, registry: SourceRegistry, llm) -> dict:
    """Run a single question through the agent WITHOUT experience cache."""
    callbacks = CallbackManager()
    events: list[dict] = []
    callbacks.add_listener(lambda e: events.append({
        "type": e.type,
        "data": e.data,
        "ts": round(e.timestamp, 3),
    }))

    start = time.time()
    try:
        state = await run_agent(
            question=question,
            registry=registry,
            llm=llm,
            callbacks=callbacks,
            experience_cache=None,   # NO CACHE
            staging_store=None,      # NO STAGING
        )
        elapsed = time.time() - start

        # Extract plan info
        plan = state.get("plan", {})
        steps = plan.get("steps", [])
        failed_steps = sum(1 for s in steps if s.get("status") == "failed")

        return {
            "response": state.get("response", ""),
            "mode": state.get("query_mode", ""),
            "artifacts": state.get("artifacts", []),
            "execution_log": state.get("execution_log", []),
            "elapsed_s": round(elapsed, 2),
            "events": events,
            "error": None,
            "plan": {
                "analysis": plan.get("analysis", ""),
                "approach": plan.get("approach", ""),
                "step_count": len(steps),
                "steps": [
                    {
                        "step_number": s.get("step_number"),
                        "action": s.get("action"),
                        "description": s.get("description", ""),
                        "status": s.get("status"),
                        "code": s.get("code", "")[:500],
                    }
                    for s in steps
                ],
            },
            "step_count": len(steps),
            "failed_steps": failed_steps,
        }
    except Exception as e:
        elapsed = time.time() - start
        return {
            "response": "",
            "mode": "",
            "artifacts": [],
            "execution_log": [],
            "elapsed_s": round(elapsed, 2),
            "events": events,
            "error": str(e),
            "plan": {},
            "step_count": 0,
            "failed_steps": 0,
        }


def load_partial_results() -> dict[int, dict]:
    """Load partial results from a previous interrupted run."""
    if RESULTS_PATH.exists():
        try:
            data = json.loads(RESULTS_PATH.read_text())
            return {r["id"]: r for r in data if "id" in r}
        except (json.JSONDecodeError, KeyError):
            pass
    return {}


def save_results(results: list[dict]) -> None:
    """Save results to JSON file."""
    RESULTS_PATH.write_text(json.dumps(results, indent=2, default=str))


async def main():
    db_url = os.environ.get("MCPDB_DATABASE_URL")
    gemini_key = os.environ.get("GEMINI_API_KEY")

    if not db_url:
        print("ERROR: MCPDB_DATABASE_URL not set")
        sys.exit(1)
    if not gemini_key:
        print("ERROR: GEMINI_API_KEY not set")
        sys.exit(1)

    resume = "--resume" in sys.argv

    print(f"Database: {db_url}")
    print(f"Questions: {len(QUESTIONS)}")
    print(f"Cache: DISABLED")
    print(f"Resume: {resume}")
    print()

    # Compute ground truth
    print("Computing ground truth SQL answers...")
    engine = sqlalchemy.create_engine(db_url)
    ground_truth = compute_ground_truth(engine)
    engine.dispose()

    gt_errors = sum(1 for gt in ground_truth.values() if gt.get("error"))
    print(f"Ground truth computed: {len(ground_truth)} questions, {gt_errors} SQL errors")

    # Load partial results if resuming
    completed: dict[int, dict] = {}
    if resume:
        completed = load_partial_results()
        if completed:
            print(f"Resuming: {len(completed)} questions already completed")

    # Set up agent
    print("Setting up agent...")
    registry = SourceRegistry()
    source = DatabaseSource(db_url)
    registry.add_source(source)

    llm = create_provider("gemini", "gemini-2.5-pro", gemini_key)
    print(f"LLM: gemini-2.5-pro (no cache)")
    print()

    # Run all questions
    all_results: list[dict] = []
    scores: list[float] = []
    errors: list[dict] = []
    total_start = time.time()

    for i, question in enumerate(QUESTIONS):
        qid = question["id"]

        # Skip if already completed (resume mode)
        if qid in completed:
            result = completed[qid]
            all_results.append(result)
            scores.append(result.get("score", 0))
            if result.get("score", 0) < 1:
                errors.append(result)
            print(f"[{i+1:3d}/100] Q{qid}: SKIP (resumed, score={result.get('score', '?')})")
            continue

        print(f"[{i+1:3d}/100] Q{qid}: {question['q'][:60]}...", end=" ", flush=True)

        agent_result = await run_agent_nocache(question["q"], registry, llm)

        gt = ground_truth.get(qid, {})
        eval_result = evaluate_response(question, gt, agent_result)

        # Enhance with extra metadata
        eval_result["category"] = CATEGORY_MAP.get(qid, "Unknown")
        eval_result["ground_truth_sql"] = question["sql"]
        eval_result["ground_truth_value"] = str(gt.get("value", ""))[:200]
        eval_result["agent_response"] = agent_result.get("response", "")[:2000]
        eval_result["execution_log"] = agent_result.get("execution_log", [])
        eval_result["plan"] = agent_result.get("plan", {})
        eval_result["events"] = agent_result.get("events", [])
        eval_result["step_count"] = agent_result.get("step_count", 0)
        eval_result["failed_steps"] = agent_result.get("failed_steps", 0)

        all_results.append(eval_result)
        scores.append(eval_result["score"])

        status = "PASS" if eval_result["score"] >= 1 else ("PARTIAL" if eval_result["score"] > 0 else "FAIL")
        print(f"{status} ({eval_result['elapsed_s']}s, {eval_result['mode']}) — {eval_result['reason'][:60]}")

        if eval_result["score"] < 1:
            errors.append(eval_result)

        # Save after each question for crash recovery
        save_results(all_results)

        # Rate limiting for Gemini API
        await asyncio.sleep(0.5)

    total_elapsed = time.time() - total_start

    # Summary
    print("\n" + "=" * 80)
    total = len(scores)
    passed = sum(1 for s in scores if s >= 1)
    partial = sum(1 for s in scores if 0 < s < 1)
    failed = sum(1 for s in scores if s == 0)
    avg_score = sum(scores) / total if total else 0

    print(f"Results: {passed} PASS, {partial} PARTIAL, {failed} FAIL out of {total}")
    print(f"Average score: {avg_score:.2%}")
    print(f"Success rate: {passed/total:.1%}")
    print(f"Total time: {total_elapsed:.0f}s ({total_elapsed/60:.1f}m)")

    # By-category breakdown
    print(f"\n{'Category':<15} {'Pass':>5} {'Partial':>8} {'Fail':>5} {'Total':>6} {'Rate':>6}")
    print("-" * 50)
    for cat in ["Counts", "Aggregation", "Filtering", "Top-N", "Dates", "Joins", "Complex", "Domain"]:
        cat_results = [r for r in all_results if r.get("category") == cat]
        if not cat_results:
            continue
        cp = sum(1 for r in cat_results if r["score"] >= 1)
        cpp = sum(1 for r in cat_results if 0 < r["score"] < 1)
        cf = sum(1 for r in cat_results if r["score"] == 0)
        ct = len(cat_results)
        print(f"{cat:<15} {cp:>5} {cpp:>8} {cf:>5} {ct:>6} {cp/ct:>5.0%}")

    # By-mode breakdown
    print(f"\n{'Mode':<15} {'Pass':>5} {'Partial':>8} {'Fail':>5} {'Total':>6} {'Avg(s)':>7}")
    print("-" * 50)
    modes = sorted(set(r.get("mode", "?") for r in all_results))
    for mode in modes:
        mode_results = [r for r in all_results if r.get("mode") == mode]
        if not mode_results:
            continue
        mp = sum(1 for r in mode_results if r["score"] >= 1)
        mpp = sum(1 for r in mode_results if 0 < r["score"] < 1)
        mf = sum(1 for r in mode_results if r["score"] == 0)
        mt = len(mode_results)
        mavg = sum(r.get("elapsed_s", 0) for r in mode_results) / mt
        print(f"{mode:<15} {mp:>5} {mpp:>8} {mf:>5} {mt:>6} {mavg:>6.1f}")

    # Save final results
    save_results(all_results)
    print(f"\nResults saved to {RESULTS_PATH}")

    # Print failures
    if errors:
        print(f"\n{'='*80}")
        print(f"FAILURES AND PARTIAL ({len(errors)}):")
        print(f"{'='*80}")
        for err in errors:
            print(f"\nQ{err['id']}: {err['question']}")
            print(f"  Category: {err.get('category')}, Type: {err['type']}, Mode: {err['mode']}, Score: {err['score']}")
            print(f"  Reason: {err['reason']}")
            if err.get('expected'):
                print(f"  Expected: {err['expected']}")
            if err.get('ground_truth_value'):
                print(f"  GT Value: {err['ground_truth_value']}")
            print(f"  Response: {err.get('agent_response', '')[:200]}")
            print(f"  Steps: {err.get('step_count', 0)} total, {err.get('failed_steps', 0)} failed")

    registry.close_all()


if __name__ == "__main__":
    asyncio.run(main())
