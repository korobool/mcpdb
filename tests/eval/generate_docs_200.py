"""Generate rich markdown documentation from 200-question eval results.

Produces per-question docs with:
- Question text and category
- Ground truth SQL (code block)
- Ground truth answer with data insight
- Agent's code (SQL/Python from execution log)
- Scoring analysis
- Pattern notes for RAG/experience cache

Usage:
    python tests/eval/generate_docs_200.py [path/to/eval_200_results.json]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).parent
PROJECT_ROOT = EVAL_DIR.parents[1]
DOCS_DIR = PROJECT_ROOT / "docs" / "eval" / "eval_200"
QUESTIONS_DIR = DOCS_DIR / "questions"

sys.path.insert(0, str(EVAL_DIR))
from questions_200 import QUESTIONS_200, CATEGORY_MAP_200

CATEGORY_DESCRIPTIONS = {
    "Frequency": "Claims frequency, trends, and seasonal patterns",
    "Cost": "MC estimate cost severity, structure, and percentiles",
    "Parts": "Damage lines, part resolution, repair severity",
    "Supplier": "Expense analysis, supplier concentration, cost types",
    "Repair": "Repair shop performance, cycle time, completion",
    "MC_vs_N24": "Regulatory (N24) vs catalog (MC) estimate comparison",
    "CycleTime": "Claim lifecycle timing and process analysis",
    "DataQuality": "Referential integrity, domain constraints, temporal sanity",
    "Geographic": "Location-based cost and frequency analysis",
    "Complex": "Multi-table actuarial analysis, segmentation, mart queries",
}

QUESTIONS_BY_ID = {q["id"]: q for q in QUESTIONS_200}


def load_results(path: Path | None = None) -> list[dict]:
    p = path or EVAL_DIR / "eval_200_results.json"
    if not p.exists():
        print(f"ERROR: {p} not found. Run eval first.")
        sys.exit(1)
    return json.loads(p.read_text())


def _extract_agent_code(result: dict) -> list[dict]:
    """Extract code blocks from agent execution log and plan."""
    blocks = []
    # From execution log
    for entry in result.get("execution_log", []):
        code = entry.get("code", "")
        if code:
            action = entry.get("action", "unknown")
            lang = "sql" if action == "sql" else "python"
            status = entry.get("status", "?")
            blocks.append({"lang": lang, "code": code, "status": status})
    # From plan steps
    plan = result.get("plan", {})
    for step in plan.get("steps", []):
        code = step.get("code", "")
        if code:
            action = step.get("action", "unknown")
            lang = "sql" if action == "sql" else "python"
            status = step.get("status", "?")
            blocks.append({"lang": lang, "code": code, "status": status})
    return blocks


def _generate_insight(question: dict, result: dict) -> str:
    """Generate a brief insight about the correct answer and pattern."""
    qid = question["id"]
    cat = CATEGORY_MAP_200.get(qid, "Unknown")
    qtype = question["type"]
    sql = question["sql"]

    insights = []

    # Pattern detection
    if "WITH latest_mc AS" in sql:
        insights.append("Uses **latest MC estimate** pattern (MAX invcalc_id per opis_id, type='mc')")
    if "WITH latest AS" in sql and "type, MAX" in sql:
        insights.append("Uses **latest estimate per type** pattern (MAX invcalc_id per opis_id+type)")
    if "COALESCE(pi.part_name, pf.part_name)" in sql:
        insights.append("Uses **part name resolution** across catalogs (SC < 10M, Free >= 20M)")
    if "srv_mc_horizon_brand" in sql:
        insights.append("Resolves **brand names** via `srv_mc_horizon_brand` join on `car_mc_brand`")
    if "DATEDIFF" in sql:
        insights.append("Uses **MySQL DATEDIFF** for date arithmetic")
    if "LEFT JOIN" in sql and "IS NULL" in sql:
        insights.append("Uses **anti-join** pattern (LEFT JOIN + IS NULL) for orphan detection")
    if "NULLIF" in sql:
        insights.append("Uses **NULLIF** to prevent division by zero")
    if "ROW_NUMBER" in sql:
        insights.append("Uses **ROW_NUMBER** window function for percentile calculation")
    if "item_id=0" in sql or "item_id = 0" in sql:
        insights.append("Checks **document-level expenses** (item_id=0, unlinked to specific parts)")
    if "service_discall" in sql:
        insights.append("Uses `service_discall` for **total discount** from estimate header")

    # Category-specific insights
    if cat == "DataQuality":
        insights.append("**Data quality check** — validates referential integrity or domain constraints")
    elif cat == "MC_vs_N24":
        insights.append("**Regulatory comparison** — MC (MultiCat) vs N24 (regulatory) estimate types")

    # Type-specific
    if qtype == "count":
        gt_val = result.get("ground_truth_value", "")
        if gt_val and gt_val != "None":
            insights.append(f"Expected count: **{gt_val}**")
    elif qtype == "numeric":
        gt_val = result.get("ground_truth_value", "")
        if gt_val and gt_val != "None":
            insights.append(f"Expected value: **{gt_val}**")

    return "\n".join(f"- {i}" for i in insights) if insights else "- Standard query pattern"


def generate_question_doc(result: dict) -> str:
    """Generate rich markdown for a single question."""
    qid = result["id"]
    question = QUESTIONS_BY_ID.get(qid, {})
    cat = result.get("category", CATEGORY_MAP_200.get(qid, "Unknown"))
    score = result.get("score", 0)
    status = "PASS" if score >= 1 else ("PARTIAL" if score > 0 else "FAIL")

    lines = [
        f"# Q{qid:03d}: {result.get('question', question.get('q', '?'))}",
        "",
        f"**Category:** {cat} — {CATEGORY_DESCRIPTIONS.get(cat, '')}  ",
        f"**Type:** {result.get('type', question.get('type', '?'))}  ",
        f"**Result:** {status} (score={score})  ",
        f"**Mode:** {result.get('mode', '?')}  ",
        f"**Time:** {result.get('elapsed_s', '?')}s  ",
        "",
        "---",
        "",
        "## Ground Truth",
        "",
        "### SQL",
        "```sql",
        question.get("sql", result.get("ground_truth_sql", "N/A")),
        "```",
        "",
    ]

    # GT answer
    gt_val = result.get("ground_truth_value", "")
    gt_rows = result.get("ground_truth_rows", "")
    if gt_val and gt_val != "None":
        lines.extend([
            f"### Answer",
            f"```",
            f"{gt_val}",
            f"```",
            "",
        ])
    if gt_rows and gt_rows != "[]":
        lines.extend([
            "### Result Rows (sample)",
            "```",
            gt_rows[:500],
            "```",
            "",
        ])

    # Insights
    lines.extend([
        "### Patterns & Insights",
        "",
        _generate_insight(question, result),
        "",
        "---",
        "",
    ])

    # Agent code
    code_blocks = _extract_agent_code(result)
    if code_blocks:
        lines.extend([
            "## Agent Execution",
            "",
        ])
        for i, block in enumerate(code_blocks, 1):
            status_tag = "OK" if block["status"] == "success" else block["status"]
            lines.extend([
                f"### Step {i} ({block['lang'].upper()}) — {status_tag}",
                f"```{block['lang']}",
                block["code"],
                "```",
                "",
            ])
    else:
        lines.extend([
            "## Agent Execution",
            "",
            "_No execution log available._",
            "",
        ])

    # Agent response
    agent_resp = result.get("agent_response", "")
    if agent_resp:
        lines.extend([
            "## Agent Response",
            "",
            agent_resp[:2000],
            "",
        ])

    # Scoring
    lines.extend([
        "---",
        "",
        "## Scoring",
        "",
        f"**Reason:** {result.get('reason', 'N/A')}  ",
    ])
    if result.get("expected"):
        lines.append(f"**Expected:** {result['expected']}  ")
    if result.get("error"):
        lines.append(f"**Error:** {result['error']}  ")
    lines.append("")

    return "\n".join(lines)


def generate_summary(results: list[dict]) -> str:
    """Generate the summary report."""
    total = len(results)
    passed = sum(1 for r in results if r["score"] >= 1)
    partial = sum(1 for r in results if 0 < r["score"] < 1)
    failed = sum(1 for r in results if r["score"] == 0)
    avg_score = sum(r["score"] for r in results) / total if total else 0
    total_time = sum(r.get("elapsed_s", 0) for r in results)

    lines = [
        "# Extended Eval Results (Q101-Q300)",
        "",
        f"**Questions:** {total} (Q101-Q300)  ",
        "**LLM:** Gemini 2.5 Pro  ",
        "**Cache:** Disabled  ",
        "",
        "## Overall Results",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| **Pass** | {passed} ({passed/total:.1%}) |",
        f"| **Partial** | {partial} |",
        f"| **Fail** | {failed} |",
        f"| **Average Score** | {avg_score:.2%} |",
        f"| **Total Time** | {total_time:.0f}s ({total_time/60:.1f}m) |",
        "",
        "## By Category",
        "",
        "| Category | Description | Pass | Fail | Total | Rate |",
        "|----------|-------------|------|------|-------|------|",
    ]

    for cat in CATEGORY_DESCRIPTIONS:
        cat_r = [r for r in results if r.get("category") == cat]
        if not cat_r:
            continue
        cp = sum(1 for r in cat_r if r["score"] >= 1)
        cf = sum(1 for r in cat_r if r["score"] == 0)
        ct = len(cat_r)
        desc = CATEGORY_DESCRIPTIONS[cat][:40]
        lines.append(f"| {cat} | {desc} | {cp} | {cf} | {ct} | {cp/ct:.0%} |")
    lines.append("")

    # By type
    lines.extend([
        "## By Question Type",
        "",
        "| Type | Pass | Fail | Total | Rate |",
        "|------|------|------|-------|------|",
    ])
    for qtype in sorted(set(r.get("type", "?") for r in results)):
        tr = [r for r in results if r.get("type") == qtype]
        tp = sum(1 for r in tr if r["score"] >= 1)
        tf = sum(1 for r in tr if r["score"] == 0)
        lines.append(f"| {qtype} | {tp} | {tf} | {len(tr)} | {tp/len(tr):.0%} |")
    lines.append("")

    # Failures list
    failures = [r for r in results if r["score"] < 1]
    if failures:
        lines.extend([
            "## Failures",
            "",
            "| QID | Question | Category | Type | Score | Reason |",
            "|-----|----------|----------|------|-------|--------|",
        ])
        for r in sorted(failures, key=lambda x: x["id"]):
            q_short = r.get("question", "")[:35] + "..."
            reason = r.get("reason", "")[:35]
            link = f"[Q{r['id']:03d}](questions/q{r['id']:03d}.md)"
            lines.append(f"| {link} | {q_short} | {r.get('category')} | {r.get('type')} | {r['score']} | {reason} |")
        lines.append("")

    # All questions index
    lines.extend([
        "## Question Index",
        "",
    ])
    current_cat = None
    for r in sorted(results, key=lambda x: x["id"]):
        cat = r.get("category", "?")
        if cat != current_cat:
            current_cat = cat
            lines.append(f"\n### {cat}")
            lines.append("")
        icon = "PASS" if r["score"] >= 1 else ("PARTIAL" if r["score"] > 0 else "FAIL")
        lines.append(f"- [{icon}] [Q{r['id']:03d}](questions/q{r['id']:03d}.md): {r.get('question', '')[:60]}")
    lines.append("")

    return "\n".join(lines)


def main():
    results_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    results = load_results(results_path)
    print(f"Loaded {len(results)} results")

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    QUESTIONS_DIR.mkdir(parents=True, exist_ok=True)

    for r in results:
        doc = generate_question_doc(r)
        out_path = QUESTIONS_DIR / f"q{r['id']:03d}.md"
        out_path.write_text(doc)
    print(f"Generated {len(results)} question docs in {QUESTIONS_DIR}")

    summary = generate_summary(results)
    report_path = DOCS_DIR / "README.md"
    report_path.write_text(summary)
    print(f"Generated report: {report_path}")

    print("Done!")


if __name__ == "__main__":
    main()
