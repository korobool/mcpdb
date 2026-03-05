"""Generate markdown documentation from eval results.

Reads eval_nocache_results.json and generates:
- Per-question markdown: docs/eval/questions/q001.md ... q100.md
- Summary: docs/eval/README.md
- Improvements: docs/eval/improvements.md
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).parent
PROJECT_ROOT = EVAL_DIR.parents[1]
DOCS_DIR = PROJECT_ROOT / "docs" / "eval"
QUESTIONS_DIR = DOCS_DIR / "questions"


def load_results(path: Path | None = None) -> list[dict]:
    """Load eval results JSON."""
    p = path or EVAL_DIR / "eval_nocache_results.json"
    if not p.exists():
        print(f"ERROR: {p} not found. Run eval first.")
        sys.exit(1)
    return json.loads(p.read_text())


def generate_question_doc(result: dict) -> str:
    """Generate markdown for a single question."""
    qid = result["id"]
    lines = [
        f"# Q{qid:03d}: {result['question']}",
        "",
        "## Summary",
        "",
        f"| Field | Value |",
        f"|-------|-------|",
        f"| **Score** | {result['score']} |",
        f"| **Result** | {'PASS' if result['score'] >= 1 else ('PARTIAL' if result['score'] > 0 else 'FAIL')} |",
        f"| **Type** | {result.get('type', '?')} |",
        f"| **Category** | {result.get('category', '?')} |",
        f"| **Mode** | {result.get('mode', '?')} |",
        f"| **Time** | {result.get('elapsed_s', '?')}s |",
        f"| **Steps** | {result.get('step_count', '?')} total, {result.get('failed_steps', 0)} failed |",
        "",
    ]

    # Ground truth
    lines.extend([
        "## Ground Truth",
        "",
        "**SQL:**",
        "```sql",
        result.get("ground_truth_sql", "N/A"),
        "```",
        "",
        f"**Expected Value:** `{result.get('ground_truth_value', 'N/A')}`",
        "",
    ])

    # Agent response
    lines.extend([
        "## Agent Response",
        "",
        result.get("agent_response", "(empty)"),
        "",
    ])

    # Execution log
    exec_log = result.get("execution_log", [])
    if exec_log:
        lines.extend([
            "## Execution Log",
            "",
        ])
        for entry in exec_log:
            step_num = entry.get("step_number", "?")
            action = entry.get("action", "?")
            status = entry.get("status", "?")
            time_ms = entry.get("time_ms", "?")
            lines.append(f"### Step {step_num} ({action}) — {status} ({time_ms}ms)")
            lines.append("")
            code = entry.get("code", "")
            if code:
                lang = "sql" if action == "sql" else "python"
                lines.append(f"```{lang}")
                lines.append(code)
                lines.append("```")
                lines.append("")
            preview = entry.get("result_preview", entry.get("error", ""))
            if preview:
                lines.append("**Result:**")
                lines.append("```")
                # Truncate long previews
                if len(preview) > 1000:
                    lines.append(preview[:1000] + "\n... (truncated)")
                else:
                    lines.append(preview)
                lines.append("```")
                lines.append("")

    # Scoring analysis
    lines.extend([
        "## Scoring",
        "",
        f"**Reason:** {result.get('reason', 'N/A')}",
        "",
    ])
    if result.get("expected"):
        lines.append(f"**Expected:** {result['expected']}")
        lines.append("")
    if result.get("error"):
        lines.append(f"**Error:** {result['error']}")
        lines.append("")

    return "\n".join(lines)


def generate_summary(results: list[dict]) -> str:
    """Generate the summary README.md."""
    total = len(results)
    passed = sum(1 for r in results if r["score"] >= 1)
    partial = sum(1 for r in results if 0 < r["score"] < 1)
    failed = sum(1 for r in results if r["score"] == 0)
    avg_score = sum(r["score"] for r in results) / total if total else 0
    total_time = sum(r.get("elapsed_s", 0) for r in results)

    lines = [
        "# Eval Results Summary",
        "",
        f"**Run date:** No-cache eval",
        f"**LLM:** Gemini 2.5 Pro",
        f"**Cache:** Disabled",
        "",
        "## Overall",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| **Total Questions** | {total} |",
        f"| **Pass** | {passed} |",
        f"| **Partial** | {partial} |",
        f"| **Fail** | {failed} |",
        f"| **Pass Rate** | {passed/total:.1%} |",
        f"| **Average Score** | {avg_score:.2%} |",
        f"| **Total Time** | {total_time:.0f}s ({total_time/60:.1f}m) |",
        "",
    ]

    # By category
    lines.extend([
        "## By Category",
        "",
        "| Category | Pass | Partial | Fail | Total | Rate |",
        "|----------|------|---------|------|-------|------|",
    ])
    categories = ["Counts", "Aggregation", "Filtering", "Top-N", "Dates", "Joins", "Complex", "Domain"]
    for cat in categories:
        cat_r = [r for r in results if r.get("category") == cat]
        if not cat_r:
            continue
        cp = sum(1 for r in cat_r if r["score"] >= 1)
        cpp = sum(1 for r in cat_r if 0 < r["score"] < 1)
        cf = sum(1 for r in cat_r if r["score"] == 0)
        ct = len(cat_r)
        lines.append(f"| {cat} | {cp} | {cpp} | {cf} | {ct} | {cp/ct:.0%} |")
    lines.append("")

    # By mode
    lines.extend([
        "## By Mode",
        "",
        "| Mode | Pass | Partial | Fail | Total | Avg Time |",
        "|------|------|---------|------|-------|----------|",
    ])
    modes = sorted(set(r.get("mode", "?") for r in results))
    for mode in modes:
        mr = [r for r in results if r.get("mode") == mode]
        if not mr:
            continue
        mp = sum(1 for r in mr if r["score"] >= 1)
        mpp = sum(1 for r in mr if 0 < r["score"] < 1)
        mf = sum(1 for r in mr if r["score"] == 0)
        mt = len(mr)
        mavg = sum(r.get("elapsed_s", 0) for r in mr) / mt
        lines.append(f"| {mode} | {mp} | {mpp} | {mf} | {mt} | {mavg:.1f}s |")
    lines.append("")

    # By type
    lines.extend([
        "## By Question Type",
        "",
        "| Type | Pass | Partial | Fail | Total | Rate |",
        "|------|------|---------|------|-------|------|",
    ])
    types = sorted(set(r.get("type", "?") for r in results))
    for qtype in types:
        tr = [r for r in results if r.get("type") == qtype]
        if not tr:
            continue
        tp = sum(1 for r in tr if r["score"] >= 1)
        tpp = sum(1 for r in tr if 0 < r["score"] < 1)
        tf = sum(1 for r in tr if r["score"] == 0)
        tt = len(tr)
        lines.append(f"| {qtype} | {tp} | {tpp} | {tf} | {tt} | {tp/tt:.0%} |")
    lines.append("")

    # Failures table
    failures = [r for r in results if r["score"] < 1]
    if failures:
        lines.extend([
            "## Failures",
            "",
            "| QID | Question | Type | Category | Score | Reason |",
            "|-----|----------|------|----------|-------|--------|",
        ])
        for r in sorted(failures, key=lambda x: x["id"]):
            q_short = r["question"][:40] + "..." if len(r["question"]) > 40 else r["question"]
            reason_short = r.get("reason", "")[:40]
            link = f"[Q{r['id']:03d}](questions/q{r['id']:03d}.md)"
            lines.append(f"| {link} | {q_short} | {r.get('type', '?')} | {r.get('category', '?')} | {r['score']} | {reason_short} |")
        lines.append("")

    # Timing stats
    times = [r.get("elapsed_s", 0) for r in results]
    if times:
        lines.extend([
            "## Timing",
            "",
            f"| Stat | Value |",
            f"|------|-------|",
            f"| Min | {min(times):.1f}s |",
            f"| Max | {max(times):.1f}s |",
            f"| Avg | {sum(times)/len(times):.1f}s |",
            f"| Median | {sorted(times)[len(times)//2]:.1f}s |",
            f"| Total | {sum(times):.0f}s ({sum(times)/60:.1f}m) |",
            "",
        ])

    # Links to all questions
    lines.extend([
        "## All Questions",
        "",
    ])
    for r in results:
        score_icon = "PASS" if r["score"] >= 1 else ("PARTIAL" if r["score"] > 0 else "FAIL")
        lines.append(f"- [{score_icon}] [Q{r['id']:03d}](questions/q{r['id']:03d}.md): {r['question'][:60]}")
    lines.append("")

    return "\n".join(lines)


def generate_improvements(results: list[dict], baseline: list[dict] | None = None) -> str:
    """Generate improvements report."""
    total = len(results)
    passed = sum(1 for r in results if r["score"] >= 1)
    partial = sum(1 for r in results if 0 < r["score"] < 1)
    failed = sum(1 for r in results if r["score"] == 0)

    lines = [
        "# Eval Improvements Report",
        "",
        "## Current Metrics (No-Cache Run)",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| **Pass** | {passed}/{total} ({passed/total:.1%}) |",
        f"| **Partial** | {partial}/{total} |",
        f"| **Fail** | {failed}/{total} |",
        "",
    ]

    if baseline:
        bp = sum(1 for r in baseline if r["score"] >= 1)
        bpp = sum(1 for r in baseline if 0 < r["score"] < 1)
        bf = sum(1 for r in baseline if r["score"] == 0)
        bt = len(baseline)

        lines.extend([
            "## Baseline (With Cache)",
            "",
            f"| Metric | Baseline | Current | Delta |",
            f"|--------|----------|---------|-------|",
            f"| **Pass** | {bp}/{bt} ({bp/bt:.1%}) | {passed}/{total} ({passed/total:.1%}) | {passed-bp:+d} |",
            f"| **Partial** | {bpp}/{bt} | {partial}/{total} | {partial-bpp:+d} |",
            f"| **Fail** | {bf}/{bt} | {failed}/{total} | {failed-bf:+d} |",
            "",
        ])

        # Per-question comparison
        baseline_by_id = {r["id"]: r for r in baseline}
        changed = []
        for r in results:
            b = baseline_by_id.get(r["id"])
            if b and r["score"] != b["score"]:
                changed.append((r["id"], b["score"], r["score"], r["question"]))

        if changed:
            lines.extend([
                "## Changed Questions",
                "",
                "| QID | Question | Before | After | Delta |",
                "|-----|----------|--------|-------|-------|",
            ])
            for qid, before, after, question in sorted(changed):
                delta = "improved" if after > before else "regressed"
                lines.append(f"| Q{qid:03d} | {question[:40]} | {before} | {after} | {delta} |")
            lines.append("")

    # Issues found
    failures = [r for r in results if r["score"] < 1]
    if failures:
        lines.extend([
            "## Issues Found",
            "",
        ])
        # Group by failure reason pattern
        reason_groups: dict[str, list] = {}
        for r in failures:
            reason = r.get("reason", "Unknown")
            # Simplify reason
            if "Expected" in reason and "not found" in reason:
                key = "Value mismatch"
            elif "Empty response" in reason:
                key = "Empty response"
            elif "Agent error" in reason:
                key = "Agent error"
            elif "Short response" in reason:
                key = "Short response"
            elif "Error response" in reason:
                key = "Error response"
            else:
                key = "Other"
            reason_groups.setdefault(key, []).append(r)

        for group, items in sorted(reason_groups.items(), key=lambda x: -len(x[1])):
            lines.append(f"### {group} ({len(items)} questions)")
            lines.append("")
            for r in items:
                lines.append(f"- **Q{r['id']:03d}** ({r.get('category', '?')}/{r.get('type', '?')}): {r['question'][:50]}")
                lines.append(f"  - Reason: {r.get('reason', '')[:80]}")
            lines.append("")

    # Fixes applied
    lines.extend([
        "## Fixes Applied",
        "",
        "### GT SQL Fixes",
        "- **Q85**: Fixed invalid `OFFSET (subquery)` MySQL syntax for median calculation. ",
        "  Replaced with `ROW_NUMBER()` window function approach.",
        "",
        "### Scoring Improvements",
        "- Widened numeric tolerance from 5% to 10% for ratio/percentage questions",
        "- Distribution/top-N scoring now checks for key GT values in response instead of just length",
        "",
        "### Plan Prompt Enhancements",
        "- Added ratio/percentage guidance: `AVG(a/b) != SUM(a)/SUM(b)`",
        "- Added MySQL median guidance: use `ROW_NUMBER()` window function",
        "- Added NULL handling guidance: filter NULLs before aggregation",
        "",
    ])

    # Lessons learned
    lines.extend([
        "## Lessons Learned",
        "",
        "1. **Ground truth SQL must be tested against live DB** — syntax that works in one MySQL version may fail in another",
        "2. **Data drift is real** — expected values change as the database is updated",
        "3. **Scoring tolerance matters** — strict 5% tolerance misses valid results for ratio/percentage questions",
        "4. **Distribution/top-N scoring should check values, not just length** — a long response is not necessarily correct",
        "5. **Experience cache significantly impacts results** — no-cache runs show the true LLM+agent capability",
        "",
    ])

    return "\n".join(lines)


def main():
    """Generate all documentation."""
    # Accept optional path arg
    results_path = None
    if len(sys.argv) > 1:
        results_path = Path(sys.argv[1])

    results = load_results(results_path)
    print(f"Loaded {len(results)} results")

    # Load baseline if available
    baseline = None
    baseline_path = EVAL_DIR / "eval_results.json"
    if baseline_path.exists():
        try:
            baseline = json.loads(baseline_path.read_text())
            print(f"Loaded baseline: {len(baseline)} results")
        except (json.JSONDecodeError, KeyError):
            pass

    # Create output dirs
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    QUESTIONS_DIR.mkdir(parents=True, exist_ok=True)

    # Generate per-question docs
    for r in results:
        qid = r["id"]
        doc = generate_question_doc(r)
        out_path = QUESTIONS_DIR / f"q{qid:03d}.md"
        out_path.write_text(doc)
    print(f"Generated {len(results)} question docs in {QUESTIONS_DIR}")

    # Generate summary
    summary = generate_summary(results)
    readme_path = DOCS_DIR / "README.md"
    readme_path.write_text(summary)
    print(f"Generated summary: {readme_path}")

    # Generate improvements
    improvements = generate_improvements(results, baseline)
    improvements_path = DOCS_DIR / "improvements.md"
    improvements_path.write_text(improvements)
    print(f"Generated improvements: {improvements_path}")

    print("Done!")


if __name__ == "__main__":
    main()
