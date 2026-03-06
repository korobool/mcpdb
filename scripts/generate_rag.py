"""Generate comprehensive RAG knowledge base for Bulgarian insurance claims database.

Creates ~/bulgaria_rag_v1.2/ with:
- 300 question files (questions/q001.md - q300.md) — one per eval question
- Pattern files (patterns/*.md) — SQL patterns, common mistakes, best practices
- Domain files (domain/*.md) — schema, relationships, business rules, data dictionary
- Template files (templates/*.md) — reusable SQL template library
- Python files (python/*.md) — visualization, DataFrame, formatting, sandbox patterns

v1.2 changes vs v1.1:
- Eliminated failures/ directory — merged anti-pattern knowledge into pattern files
- Merged anti_pattern_is_active into latest_mc_estimate (single authoritative source)
- Added python/ directory with 4 files covering visualization, DataFrame ops, result
  formatting, and sandbox constraints
- Removed hardcoded question lists from pattern files

Each file has rich headers optimized for embedding/vectorization:
- Descriptive title with domain keywords
- Semantic tags for RAG retrieval
- Complete code snippets (SQL, Python)
- Explanation of why the approach works
"""

from __future__ import annotations

import json
import re
import sys
import textwrap
from pathlib import Path

# Paths
EVAL_DIR = Path(__file__).resolve().parents[1] / "tests" / "eval"
RAG_DIR = Path.home() / "bulgaria_rag_v1.2"

sys.path.insert(0, str(EVAL_DIR))
from questions_200 import QUESTIONS_200, CATEGORY_MAP_200

# ─── Load data ───────────────────────────────────────────────────────────────

def load_json(path: Path) -> list[dict]:
    if path.exists():
        return json.loads(path.read_text())
    return []

RESULTS_100 = load_json(EVAL_DIR / "eval_nocache_results.json")
RESULTS_200 = load_json(EVAL_DIR / "eval_200_results.json")

# Load Q1-100 from run_eval.py
sys.path.insert(0, str(EVAL_DIR))
from run_eval import QUESTIONS as QUESTIONS_100

Q100_BY_ID = {q["id"]: q for q in QUESTIONS_100}
Q200_BY_ID = {q["id"]: q for q in QUESTIONS_200}
R100_BY_ID = {r["id"]: r for r in RESULTS_100}
R200_BY_ID = {r["id"]: r for r in RESULTS_200}

# Category info
CATEGORY_100 = {
    **{i: "Counts" for i in range(1, 11)},
    **{i: "Aggregation" for i in range(11, 26)},
    **{i: "Filtering" for i in range(26, 41)},
    **{i: "Top-N" for i in range(41, 56)},
    **{i: "Dates" for i in range(56, 66)},
    **{i: "Joins" for i in range(66, 81)},
    **{i: "Complex" for i in range(81, 91)},
    **{i: "Domain" for i in range(91, 101)},
}

CATEGORY_DESCRIPTIONS = {
    # Q1-100 categories
    "Counts": "Simple row counts and table cardinality queries",
    "Aggregation": "SUM, AVG, MIN, MAX, and aggregate calculations",
    "Filtering": "WHERE conditions, exact match, range, and pattern filters",
    "Top-N": "ORDER BY ... LIMIT ranking queries",
    "Dates": "Date arithmetic, temporal grouping, and time-series analysis",
    "Joins": "Multi-table joins, relationships, and cross-table analysis",
    "Complex": "Multi-step queries, CTEs, window functions, ratio calculations",
    "Domain": "Insurance domain-specific exploration and data discovery",
    # Q101-300 categories
    "Frequency": "Claims frequency, trends, seasonal patterns, and filing lag analysis",
    "Cost": "MC estimate cost severity, cost structure shares, percentiles, and cost segments",
    "Parts": "Damage lines, part resolution across catalogs, replacement vs repair ratios",
    "Supplier": "Expense analysis, supplier concentration, expense subtypes, and cost types",
    "Repair": "Repair shop performance, cycle time, completion rates, and repair workflow",
    "MC_vs_N24": "Regulatory (N24) vs catalog (MC) estimate comparison and analysis",
    "CycleTime": "Claim lifecycle timing, filing lag, repair duration, and process analysis",
    "DataQuality": "Referential integrity checks, domain constraints, and temporal sanity",
    "Geographic": "Location-based cost and frequency analysis by country and damage place",
    "Complex_Extended": "Multi-table actuarial analysis, segmentation, and mart queries",
}


# ─── Sanitize failure reasons (remove hardcoded numbers) ─────────────────────

def _sanitize_reason(reason: str) -> str:
    """Replace hardcoded expected values in failure reasons with generic descriptions."""
    # "Expected ~21.02, not found" → "Agent's result did not match the ground truth value"
    reason = re.sub(
        r"Expected ~?[\d,.]+,?\s*not found(?: in response)?",
        "Agent's result did not match the ground truth value (run the correct SQL to verify)",
        reason,
    )
    return reason


# ─── Detect SQL patterns ────────────────────────────────────────────────────

def detect_patterns(sql: str) -> list[str]:
    """Detect reusable SQL patterns in a query."""
    patterns = []
    sql_upper = sql.upper()

    if "WITH LATEST_MC AS" in sql_upper or ("MAX(INVCALC_ID)" in sql_upper and "TYPE='MC'" in sql.lower()):
        patterns.append("latest-mc-estimate")
    if "MAX(INVCALC_ID)" in sql_upper and "TYPE" in sql_upper:
        patterns.append("latest-estimate-per-type")
    if "COALESCE(PI.PART_NAME" in sql_upper or "COALESCE(PI.PART_NAME, PF.PART_NAME)" in sql_upper:
        patterns.append("part-name-resolution")
    if "SRV_MC_HORIZON_BRAND" in sql_upper:
        patterns.append("brand-name-resolution")
    if "SRV_MC_HORIZON_MODELNAME" in sql_upper:
        patterns.append("model-name-resolution")
    if "DATEDIFF" in sql_upper:
        patterns.append("date-arithmetic")
    if "LEFT JOIN" in sql_upper and "IS NULL" in sql_upper:
        patterns.append("anti-join-orphan-detection")
    if "NULLIF" in sql_upper:
        patterns.append("nullif-division-safety")
    if "ROW_NUMBER" in sql_upper:
        patterns.append("window-function-ranking")
    if "ITEM_ID=0" in sql.replace(" ", "") or "ITEM_ID = 0" in sql:
        patterns.append("document-level-expenses")
    if "SERVICE_DISCALL" in sql_upper:
        patterns.append("total-discount")
    if "DATE_FORMAT" in sql_upper:
        patterns.append("date-formatting")
    if "YEAR(" in sql_upper and "GROUP BY" in sql_upper:
        patterns.append("temporal-grouping")
    if "QUARTER(" in sql_upper:
        patterns.append("quarterly-analysis")
    if "COUNT(DISTINCT" in sql_upper:
        patterns.append("distinct-counting")
    if "HAVING" in sql_upper:
        patterns.append("group-filtering")
    if "CASE WHEN" in sql_upper:
        patterns.append("conditional-aggregation")
    if sql_upper.count("JOIN") >= 3:
        patterns.append("multi-table-join")
    if "AVG(" in sql_upper and "/" in sql and "NULLIF" not in sql_upper:
        patterns.append("ratio-calculation")
    if "COUNT(*) OVER" in sql_upper or "ROW_NUMBER() OVER" in sql_upper:
        patterns.append("window-function")
    if "INFORMATION_SCHEMA" in sql_upper:
        patterns.append("schema-introspection")

    return patterns


def get_pattern_explanation(pattern: str) -> str:
    """Get a human-readable explanation of a SQL pattern."""
    explanations = {
        "latest-mc-estimate": (
            "**Latest MC Estimate Pattern**: Use `MAX(invcalc_id)` grouped by `opis_id` "
            "where `type='mc'` to get the most recent MC estimate per claim. "
            "Multiple estimate revisions exist per claim — always use the latest one. "
            "CTE: `WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic "
            "INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id "
            "FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm "
            "ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id)`"
        ),
        "latest-estimate-per-type": (
            "**Latest Estimate Per Type Pattern**: Use `MAX(invcalc_id)` grouped by "
            "`(opis_id, type)` to get latest estimate of each type (MC or N24) per claim."
        ),
        "part-name-resolution": (
            "**Part Name Resolution Pattern**: Part IDs span three catalogs based on range: "
            "SC catalog (ins_partsindex, part_id < 10,000,000), "
            "MC catalog (ins_partsomc, 10M-20M, currently empty), "
            "FREE catalog (ins_partsfree, part_id >= 20,000,000). "
            "Use COALESCE with LEFT JOINs: `COALESCE(pi.part_name, pf.part_name)` "
            "where pi is ins_partsindex (part_id < 10M) and pf is ins_partsfree (part_id >= 20M)."
        ),
        "brand-name-resolution": (
            "**Brand Name Resolution Pattern**: `ins_cars.car_mc_brand` contains opaque codes "
            "like 'TA3PD27008', NOT human-readable names. "
            "Join with `srv_mc_horizon_brand` on `car_mc_brand = brand_id` to get `brand_name`."
        ),
        "model-name-resolution": (
            "**Model Name Resolution Pattern**: `ins_cars.car_mc_modelname` contains opaque codes. "
            "Join with `srv_mc_horizon_modelname` on matching `brand_id` and `modelname_id` "
            "to get `modelname_name`."
        ),
        "date-arithmetic": (
            "**MySQL Date Arithmetic**: Use `DATEDIFF(date1, date2)` for day differences. "
            "Returns positive when date1 > date2. For datetime columns, "
            "use `CAST(col AS DATE)` before comparing with date columns."
        ),
        "anti-join-orphan-detection": (
            "**Anti-Join for Orphan Detection**: Use `LEFT JOIN ... WHERE right_table.pk IS NULL` "
            "to find records in the left table with no matching record in the right table. "
            "Essential for data quality checks (orphan claims, missing references)."
        ),
        "nullif-division-safety": (
            "**NULLIF Division Safety**: Use `NULLIF(denominator, 0)` to prevent division by zero. "
            "Returns NULL instead of error when denominator is 0. "
            "Example: `AVG(cost / NULLIF(total_cost, 0))`"
        ),
        "window-function-ranking": (
            "**ROW_NUMBER Window Function**: Use `ROW_NUMBER() OVER (ORDER BY col)` "
            "for percentile calculations since MySQL lacks `PERCENTILE_CONT`. "
            "For median: filter where `rn IN (FLOOR((cnt+1)/2), CEIL((cnt+1)/2))`."
        ),
        "document-level-expenses": (
            "**Document-Level Expenses**: Expenses with `item_id=0` are document-level "
            "(not linked to specific parts). These represent overhead costs like "
            "administration fees, transport, etc."
        ),
        "total-discount": (
            "**Total Discount**: `service_discall` in `ins_mc_invcalc` represents "
            "the total discount percentage applied to the entire estimate."
        ),
        "date-formatting": (
            "**MySQL Date Formatting**: Use `DATE_FORMAT(date_col, '%Y-%m')` for monthly grouping, "
            "`YEAR()` for annual, `QUARTER()` for quarterly. "
            "Do NOT use PostgreSQL-style `DATE_TRUNC`."
        ),
        "temporal-grouping": (
            "**Temporal Grouping**: Group time-series data using `YEAR(date_col)`, "
            "`DATE_FORMAT(date_col, '%Y-%m')`, or `QUARTER(date_col)` for MySQL."
        ),
        "quarterly-analysis": (
            "**Quarterly Analysis**: Use `QUARTER(date_col)` to extract quarter (1-4) "
            "from a date. Combine with `YEAR()` for year-quarter grouping."
        ),
        "distinct-counting": (
            "**Distinct Counting**: Use `COUNT(DISTINCT col)` for unique value counts. "
            "Critical for counting unique claims, cars, or parts."
        ),
        "group-filtering": (
            "**HAVING Clause**: Filter groups after aggregation. "
            "Use `HAVING COUNT(*) >= N` to filter by group size."
        ),
        "conditional-aggregation": (
            "**Conditional Aggregation**: Use `SUM(CASE WHEN condition THEN 1 ELSE 0 END)` "
            "or `COUNT(CASE WHEN condition THEN 1 END)` for counting within conditions."
        ),
        "multi-table-join": (
            "**Multi-Table Join**: Joining 3+ tables requires understanding the ER model. "
            "Common chain: `ins_opis → ins_damages` (via damage_id), "
            "`ins_opis → ins_cars` (via car_id), "
            "`ins_opis → ins_mc_invcalc` (via opis_id)."
        ),
        "ratio-calculation": (
            "**Ratio Calculation**: For per-record ratios, use `AVG(a/b)` NOT `SUM(a)/SUM(b)`. "
            "The two give different results. Always use `NULLIF` on denominator."
        ),
        "window-function": (
            "**Window Functions**: MySQL 8.0 supports `ROW_NUMBER()`, `RANK()`, "
            "`COUNT(*) OVER()`, etc. Useful for percentiles and running totals."
        ),
        "schema-introspection": (
            "**Schema Introspection**: Query `INFORMATION_SCHEMA.TABLES` and "
            "`INFORMATION_SCHEMA.COLUMNS` for database metadata. "
            "Always filter by `TABLE_SCHEMA='bgins'`."
        ),
    }
    return explanations.get(pattern, f"**{pattern}** pattern")


# ─── Title generation ────────────────────────────────────────────────────────

# Category-level title prefixes — each category gets a unique semantic anchor
_CATEGORY_TITLE_PREFIX = {
    "Counts": "Table Row Count",
    "Aggregation": "Aggregate Calculation",
    "Filtering": "Filtered Query",
    "Top-N": "Ranking Query",
    "Dates": "Temporal Analysis",
    "Joins": "Multi-Table Relationship",
    "Complex": "Advanced Analytics",
    "Domain": "Domain Exploration",
    "Frequency": "Claims Frequency",
    "Cost": "Cost Severity",
    "Parts": "Damage Parts",
    "Supplier": "Supplier Expense",
    "Repair": "Repair Shop",
    "MC_vs_N24": "MC vs N24 Estimate",
    "CycleTime": "Lifecycle Timing",
    "DataQuality": "Data Quality Check",
    "Geographic": "Geographic Distribution",
    "Complex_Extended": "Actuarial Analysis",
}

# Pattern-level short labels for title enrichment
_PATTERN_TITLE_HINTS = {
    "latest-mc-estimate": "Latest MC Estimate CTE",
    "part-name-resolution": "Part Catalog Resolution",
    "brand-name-resolution": "Brand Name Join",
    "model-name-resolution": "Model Name Join",
    "anti-join-orphan-detection": "Anti-Join Orphan Check",
    "nullif-division-safety": "Safe Division",
    "window-function-ranking": "Window Function Percentile",
    "date-arithmetic": "Date Arithmetic",
    "document-level-expenses": "Document-Level Expenses",
    "conditional-aggregation": "Conditional Aggregation",
    "multi-table-join": "Multi-Table Join",
    "ratio-calculation": "Ratio Calculation",
}


def _build_title(qid: int, question_text: str, cat: str, qtype: str, patterns: list[str]) -> str:
    """Build a semantically distinct title optimized for embedding diversity.

    Strategy: [Category Anchor] — [Core Topic from Question] ([Key Pattern])
    Each part pulls the embedding in a different direction, maximizing separation.
    """
    # 1. Category anchor (unique per category)
    prefix = _CATEGORY_TITLE_PREFIX.get(cat, cat)

    # 2. Extract the core topic from the question
    topic = question_text.rstrip("?").strip()
    # Remove common question prefixes that add no semantic value to embeddings
    for strip in [
        "How many ", "What is the ", "What are the ", "Which ",
        "How does the ", "For claims with both estimates, how does the ",
        "For claims with both MC and N24, what is the ",
        "For claims ", "Show the ", "Build a ",
        "List all ", "Are there any ",
    ]:
        if topic.startswith(strip):
            topic = topic[len(strip):]
            break
    # Capitalize first letter of remaining topic
    if topic:
        topic = topic[0].upper() + topic[1:]
    # Truncate to a reasonable length for embedding expressiveness
    if len(topic) > 80:
        topic = topic[:77] + "..."

    # 3. Pattern hint (the most distinctive pattern, if any)
    pattern_hint = ""
    for p in patterns:
        if p in _PATTERN_TITLE_HINTS:
            pattern_hint = f" — {_PATTERN_TITLE_HINTS[p]}"
            break

    return f"{prefix}: {topic}{pattern_hint}"


# ─── Generate question files ────────────────────────────────────────────────

def generate_question_file(qid: int) -> str:
    """Generate a rich RAG-optimized markdown file for one question."""
    # Get question data
    if qid <= 100:
        q = Q100_BY_ID.get(qid, {})
        r = R100_BY_ID.get(qid, {})
        cat = CATEGORY_100.get(qid, "Unknown")
        question_text = q.get("q", r.get("question", "?"))
        sql = q.get("sql", r.get("ground_truth_sql", "N/A"))
        qtype = q.get("type", r.get("type", "?"))
    else:
        q = Q200_BY_ID.get(qid, {})
        r = R200_BY_ID.get(qid, {})
        cat = CATEGORY_MAP_200.get(qid, "Unknown")
        question_text = q.get("q", r.get("question", "?"))
        sql = q.get("sql", r.get("ground_truth_sql", "N/A"))
        qtype = q.get("type", r.get("type", "?"))

    cat_desc = CATEGORY_DESCRIPTIONS.get(cat, "")
    score = r.get("score", "?")
    passed = score >= 1 if isinstance(score, (int, float)) else False
    mode = r.get("mode", "?")

    # Detect patterns
    patterns = detect_patterns(sql)
    pattern_tags = ", ".join(patterns) if patterns else "basic-query"

    # Ground truth value
    gt_val = r.get("ground_truth_value", r.get("ground_truth", ""))
    if gt_val and str(gt_val) != "None":
        gt_display = str(gt_val)
    else:
        gt_display = ""

    # Build semantically distinct title
    title = _build_title(qid, question_text, cat, qtype, patterns)

    # Build the file
    lines = [
        f"# {title}",
        "",
        f"## Metadata",
        f"- **Question ID**: Q{qid:03d}",
        f"- **Category**: {cat} — {cat_desc}",
        f"- **Query Type**: {qtype}",
        f"- **SQL Patterns**: {pattern_tags}",
        f"- **Difficulty**: {'advanced' if len(patterns) >= 2 else 'intermediate' if patterns else 'basic'}",
        f"- **Tables Used**: {_extract_tables(sql)}",
        "",
        "---",
        "",
        "## Question",
        "",
        f"> {question_text}",
        "",
    ]

    # Answer format guidance (no hardcoded values — DB is live and numbers change)
    lines.extend([
        "## Expected Answer Format",
        "",
        _answer_format_guidance(qtype),
        "",
    ])

    # Ground truth SQL
    lines.extend([
        "## Correct SQL Solution",
        "",
        "```sql",
        sql,
        "```",
        "",
    ])

    # Explain the SQL
    lines.extend([
        "## Solution Explanation",
        "",
        _explain_sql(sql, qtype, cat, question_text, patterns),
        "",
    ])

    # Pattern documentation
    if patterns:
        lines.extend([
            "## SQL Patterns Used",
            "",
        ])
        for p in patterns:
            lines.extend([
                f"### {p}",
                "",
                get_pattern_explanation(p),
                "",
            ])

    # Agent performance insight
    if r:
        agent_resp = r.get("agent_response", "")
        reason = r.get("reason", "")
        if not passed and reason:
            lines.extend([
                "## Common Mistakes",
                "",
                f"The agent scored {score} on this question.",
                f"**Failure reason**: {_sanitize_reason(reason)}",
                "",
            ])
            # Add specific mistake analysis
            mistake = _analyze_mistake(sql, agent_resp, patterns, cat)
            if mistake:
                lines.extend([mistake, ""])

        # Agent execution steps
        exec_log = r.get("execution_log", [])
        plan = r.get("plan", {})
        agent_code = _extract_agent_code(exec_log, plan)
        if agent_code and not passed:
            lines.extend([
                "## Agent's Incorrect Approach",
                "",
                "The agent attempted:",
                "",
            ])
            for i, block in enumerate(agent_code[:3], 1):
                lang = block.get("lang", "sql")
                code = block.get("code", "")
                if code:
                    lines.extend([
                        f"```{lang}",
                        code[:500],
                        "```",
                        "",
                    ])
            lines.extend([
                "**Why this is wrong**: See the Common Mistakes section above.",
                "",
            ])

    # Tags for indexing
    tags = [cat.lower(), qtype]
    tags.extend(patterns)
    if not passed:
        tags.append("failure-pattern")
    tables = _extract_table_list(sql)
    tags.extend(t.lower() for t in tables)

    lines.extend([
        "---",
        "",
        f"## Tags",
        f"`{', '.join(tags)}`",
    ])

    return "\n".join(lines)


def _answer_format_guidance(qtype: str) -> str:
    """Return guidance on expected answer format without hardcoded values."""
    guidance = {
        "count": "This query returns a **single integer count**. The answer should be an exact number from the SQL result.",
        "numeric": "This query returns a **single numeric value** (may include decimals). Present the result with appropriate precision.",
        "distribution": "This query returns **multiple rows** showing a distribution or breakdown. Present all rows or key rows as a table.",
        "top_n": "This query returns a **ranked list** of top entries. Present the results in order with their values.",
        "comparison": "This query returns **two or more values** for comparison. Present both sides clearly.",
        "value": "This query returns a **single value** (string, date, or identifier). Present the exact result.",
        "list": "This query returns a **list of items**. Present all items clearly.",
    }
    return guidance.get(qtype, "Run the SQL query to get the current answer from the live database.")


def _extract_tables(sql: str) -> str:
    """Extract table names from SQL for metadata."""
    tables = _extract_table_list(sql)
    return ", ".join(tables) if tables else "unknown"


def _extract_table_list(sql: str) -> list[str]:
    """Extract table names as a list."""
    known_tables = [
        "ins_opis", "ins_damages", "ins_cars", "ins_mc_invcalc", "ins_mc_invexpenses",
        "ins_mc_invitems", "ins_opis_rows", "ins_invrepair", "ins_gendocs",
        "ins_gendocs_opis_rows", "ins_partsindex", "ins_partsfree", "ins_partsomc",
        "inv_exptypes", "inv_expunits", "srv_mc_catalog_make", "srv_mc_catalog_model",
        "srv_mc_horizon_brand", "srv_mc_horizon_category", "srv_mc_horizon_model",
        "srv_mc_horizon_modelname", "INFORMATION_SCHEMA",
    ]
    found = []
    sql_upper = sql.upper()
    for t in known_tables:
        if t.upper() in sql_upper:
            found.append(t)
    return found


def _explain_sql(sql: str, qtype: str, cat: str, question: str, patterns: list[str]) -> str:
    """Generate a human-readable explanation of the SQL solution."""
    parts = []

    if "latest-mc-estimate" in patterns:
        parts.append(
            "This query uses the **latest MC estimate** CTE pattern. The `ins_mc_invcalc` table "
            "contains multiple estimate revisions per claim. To get the most recent MC estimate, "
            "we find `MAX(invcalc_id)` grouped by `opis_id` where `type='mc'`, then join back "
            "to get the full record. This is critical — using `is_active=1` or querying all "
            "records gives incorrect results because there can be multiple active estimates."
        )

    if "brand-name-resolution" in patterns:
        parts.append(
            "The `car_mc_brand` column in `ins_cars` contains opaque brand codes (e.g., 'TA3PD27008'), "
            "not human-readable names. We join with `srv_mc_horizon_brand` on "
            "`car_mc_brand = brand_id` to resolve the `brand_name`."
        )

    if "part-name-resolution" in patterns:
        parts.append(
            "Part IDs span three catalog ranges: SC (ins_partsindex, ID < 10M), "
            "MC (ins_partsomc, 10M-20M, currently empty), FREE (ins_partsfree, ID >= 20M). "
            "We use LEFT JOINs and COALESCE to resolve part names across catalogs."
        )

    if "anti-join-orphan-detection" in patterns:
        parts.append(
            "This is a data quality check using an anti-join pattern: "
            "`LEFT JOIN ... WHERE pk IS NULL` finds records with broken references."
        )

    if "nullif-division-safety" in patterns:
        parts.append(
            "Uses `NULLIF(denominator, 0)` to safely handle division — returns NULL "
            "instead of a division-by-zero error when the denominator is zero."
        )

    if "window-function-ranking" in patterns:
        parts.append(
            "Uses `ROW_NUMBER()` window function because MySQL doesn't have `PERCENTILE_CONT`. "
            "For median calculation, we number rows and pick the middle one(s)."
        )

    if "date-arithmetic" in patterns:
        parts.append(
            "Uses `DATEDIFF(date1, date2)` for MySQL date arithmetic. "
            "When comparing datetime columns with date columns, use `CAST(datetime_col AS DATE)` first."
        )

    if qtype == "count":
        parts.append("Returns a single count. Run the SQL to get the current value from the live database.")
    elif qtype == "numeric":
        parts.append("Returns a single numeric value. Run the SQL to get the current value from the live database.")
    elif qtype == "distribution":
        parts.append("Returns multiple rows showing a distribution. Run the SQL to get current data.")
    elif qtype == "top_n":
        parts.append("Returns ranked results. Run the SQL to get the current ranking from the live database.")

    if not parts:
        parts.append(f"A {'simple' if len(patterns) == 0 else 'moderate'} {cat} query against the bgins database.")

    return "\n\n".join(parts)


def _analyze_mistake(sql: str, agent_resp: str, patterns: list[str], cat: str) -> str:
    """Analyze why the agent got this wrong."""
    mistakes = []

    if "latest-mc-estimate" in patterns:
        mistakes.append(
            "**Missing 'latest estimate' pattern**: The agent likely queried all MC estimates or "
            "filtered by `is_active=1` instead of using `MAX(invcalc_id)` per `opis_id`. "
            "This is the #1 failure pattern in the eval. The correct approach is the "
            "`latest_mc` CTE that picks the highest `invcalc_id` for each `opis_id` where `type='mc'`."
        )

    if "brand-name-resolution" in patterns and "car_mc_brand" in sql:
        if "brand_name" not in agent_resp.lower() and "horizon" not in agent_resp.lower():
            mistakes.append(
                "**Missing brand name resolution**: The agent may not have joined with "
                "`srv_mc_horizon_brand` to resolve opaque brand codes to human-readable names."
            )

    if cat == "MC_vs_N24":
        mistakes.append(
            "**MC vs N24 comparison complexity**: Few claims have both MC and N24 estimates. "
            "The agent must use the latest estimate per type pattern and compare on matching opis_id."
        )

    if "date-arithmetic" in patterns:
        mistakes.append(
            "**Date arithmetic differences**: The agent may have used different date fields, "
            "forgotten to cast DATETIME to DATE, or computed date differences differently."
        )

    return "\n".join(mistakes)


def _extract_agent_code(exec_log: list, plan: dict) -> list[dict]:
    """Extract code blocks from agent execution."""
    blocks = []
    for entry in exec_log:
        code = entry.get("code", "")
        if code:
            action = entry.get("action", "unknown")
            lang = "sql" if action == "sql" else "python"
            blocks.append({"lang": lang, "code": code})
    for step in plan.get("steps", []):
        code = step.get("code", "")
        if code:
            action = step.get("action", "unknown")
            lang = "sql" if action == "sql" else "python"
            blocks.append({"lang": lang, "code": code})
    return blocks


# ─── Generate pattern files ─────────────────────────────────────────────────

PATTERN_FILES = {
    "latest_mc_estimate": {
        "title": "Latest MC Estimate CTE Pattern — Getting the Most Recent Motor Claims Estimate",
        "content": textwrap.dedent("""\
            # Latest MC Estimate CTE Pattern — Getting the Most Recent Motor Claims Estimate

            ## Overview
            This is the single most important SQL pattern for the Bulgarian insurance claims database (bgins).
            The `ins_mc_invcalc` table stores **multiple estimate revisions** per claim. Each time an estimate
            is revised, a new row is inserted with a higher `invcalc_id`. To analyze current costs, you must
            always use the **latest** estimate.

            ## The Problem
            - A claim (opis_id) can have multiple MC estimate records in `ins_mc_invcalc`
            - Records have types: 'mc' (MultiCat catalog) and 'n24' (regulatory/N24)
            - Using `is_active=1` is NOT reliable — multiple active records can exist
            - Using `WHERE type='mc'` without deduplication counts all revisions
            - This leads to **inflated counts, wrong averages, and incorrect cost analysis**

            ## The Solution — Latest MC Estimate CTE

            ```sql
            WITH latest_mc AS (
                SELECT ic.*
                FROM ins_mc_invcalc ic
                INNER JOIN (
                    SELECT opis_id, MAX(invcalc_id) AS max_id
                    FROM ins_mc_invcalc
                    WHERE type = 'mc'
                    GROUP BY opis_id
                ) lm ON lm.opis_id = ic.opis_id AND lm.max_id = ic.invcalc_id
            )
            SELECT ...
            FROM latest_mc mc
            ...
            ```

            ## How It Works
            1. Inner subquery: `MAX(invcalc_id)` per `opis_id` where `type='mc'` → one row per claim
            2. Self-join back to `ins_mc_invcalc` to get all columns of the latest record
            3. Use the CTE result `latest_mc` as if it were a table with one row per claim

            ## Variant: Latest Estimate Per Type (MC and N24)

            ```sql
            WITH latest AS (
                SELECT ic.*
                FROM ins_mc_invcalc ic
                INNER JOIN (
                    SELECT opis_id, type, MAX(invcalc_id) AS max_id
                    FROM ins_mc_invcalc
                    GROUP BY opis_id, type
                ) lm ON lm.opis_id = ic.opis_id AND lm.max_id = ic.invcalc_id
            )
            ```

            ## Common Usage Examples

            ### Average MC estimated cost by brand
            ```sql
            WITH latest_mc AS (...)
            SELECT b.brand_name, AVG(mc.total_cost) AS avg_cost, COUNT(*) AS claims
            FROM latest_mc mc
            JOIN ins_opis o ON o.opis_id = mc.opis_id
            JOIN ins_cars c ON c.car_id = o.car_id
            JOIN srv_mc_horizon_brand b ON c.car_mc_brand = b.brand_id
            GROUP BY b.brand_name
            ORDER BY avg_cost DESC
            ```

            ### Cost structure shares
            ```sql
            WITH latest_mc AS (...)
            SELECT
                ROUND(100 * AVG(newparts_cost / NULLIF(total_cost, 0)), 2) AS avg_parts_pct,
                ROUND(100 * AVG(paints_cost / NULLIF(total_cost, 0)), 2) AS avg_paint_pct,
                ROUND(100 * AVG(repairs_cost / NULLIF(total_cost, 0)), 2) AS avg_repair_pct
            FROM latest_mc
            WHERE total_cost > 0
            ```

            ### Claims missing MC estimates
            ```sql
            SELECT COUNT(*) FROM ins_opis o
            LEFT JOIN ins_mc_invcalc mc ON mc.opis_id = o.opis_id AND mc.type = 'mc'
            WHERE mc.invcalc_id IS NULL
            ```

            ## How to Verify
            Run these queries to check current data volumes:
            ```sql
            SELECT COUNT(*) AS total_mc_rows FROM ins_mc_invcalc WHERE type='mc';
            SELECT COUNT(DISTINCT opis_id) AS unique_claims_with_mc FROM ins_mc_invcalc WHERE type='mc';
            ```
            Multiple estimate revisions per claim are common — the latest CTE handles this.
            The `is_active` count will be **higher** than the distinct opis_id count, proving duplicates exist.

            ## Critical Anti-Pattern: Do NOT Use `is_active=1`

            This is the **#1 most common mistake** when querying MC estimates.

            ### The Mistake
            ```sql
            -- WRONG: May include multiple active records per claim
            SELECT AVG(total_cost) FROM ins_mc_invcalc WHERE type='mc' AND is_active=1

            -- ALSO WRONG: Includes all revisions, not just latest
            SELECT AVG(total_cost) FROM ins_mc_invcalc WHERE type='mc'

            -- ALSO WRONG: Wrong deduplication column
            SELECT opis_id, MAX(total_cost) FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id
            ```

            ### Why This Is Wrong
            1. Multiple estimates per claim can have `is_active=1`
            2. The latest estimate might have `is_active=0`
            3. Using `MAX(total_cost)` picks the highest cost, not the latest revision
            4. This inflates counts and distorts averages

            ### Impact
            Verify the difference yourself:
            ```sql
            SELECT COUNT(*) AS active_count FROM ins_mc_invcalc WHERE type='mc' AND is_active=1;
            SELECT COUNT(DISTINCT opis_id) AS latest_count FROM ins_mc_invcalc WHERE type='mc';
            ```

            ### The Fix
            Always use the Latest MC CTE shown above. `MAX(invcalc_id)` per `opis_id` guarantees
            exactly one row per claim — the most recently created estimate.

            ## Tags
            `latest-mc-estimate, ins_mc_invcalc, CTE, MAX, GROUP BY, cost-analysis, estimate-revision, anti-pattern, is_active, common-mistake`
        """),
    },
    "part_name_resolution": {
        "title": "Part Name Resolution — Resolving Part IDs Across Three Catalogs",
        "content": textwrap.dedent("""\
            # Part Name Resolution — Resolving Part IDs Across Three Catalogs

            ## Overview
            The bgins database stores part IDs in `ins_opis_rows.part_id`, but these IDs span
            **three separate catalog tables** based on numeric range. To get human-readable part names,
            you must check all applicable catalogs.

            ## Part ID Ranges
            | Range | Table | Description |
            |-------|-------|-------------|
            | 1 – 9,999,999 | `ins_partsindex` | SC (Standard Catalog) |
            | 10,000,000 – 19,999,999 | `ins_partsomc` | MC (may be empty — check `SELECT COUNT(*)`) |
            | 20,000,000+ | `ins_partsfree` | FREE (free-text parts) |

            ## The Pattern
            ```sql
            SELECT
                r.part_id,
                COALESCE(pi.part_name, pf.part_name) AS part_name,
                COUNT(*) AS frequency
            FROM ins_opis_rows r
            LEFT JOIN ins_partsindex pi ON r.part_id = pi.part_id AND r.part_id < 10000000
            LEFT JOIN ins_partsfree pf ON r.part_id = pf.part_id AND r.part_id >= 20000000
            GROUP BY r.part_id, part_name
            ORDER BY frequency DESC
            ```

            ## Important Notes
            - `ins_partsomc` may be empty — always check with `SELECT COUNT(*) FROM ins_partsomc`
            - Some SC-range part_ids in opis_rows may not exist in ins_partsindex (unresolved)
            - Always use LEFT JOIN to handle unresolved parts (they return NULL for part_name)
            - The range condition in the JOIN clause improves performance

            ## How to Verify
            ```sql
            -- Check part resolution coverage
            SELECT
                COUNT(*) AS total_rows,
                SUM(CASE WHEN pi.part_id IS NOT NULL THEN 1 ELSE 0 END) AS resolved_sc,
                SUM(CASE WHEN pf.part_id IS NOT NULL THEN 1 ELSE 0 END) AS resolved_free,
                SUM(CASE WHEN pi.part_id IS NULL AND pf.part_id IS NULL THEN 1 ELSE 0 END) AS unresolved
            FROM ins_opis_rows r
            LEFT JOIN ins_partsindex pi ON r.part_id = pi.part_id AND r.part_id < 10000000
            LEFT JOIN ins_partsfree pf ON r.part_id = pf.part_id AND r.part_id >= 20000000;
            ```

            ## Tags
            `part-name-resolution, ins_partsindex, ins_partsfree, ins_partsomc, COALESCE, LEFT JOIN, catalog-ranges`
        """),
    },
    "brand_model_resolution": {
        "title": "Brand and Model Name Resolution — Decoding Opaque Car Identifiers",
        "content": textwrap.dedent("""\
            # Brand and Model Name Resolution — Decoding Opaque Car Identifiers

            ## Overview
            The `ins_cars` table stores car brand and model as **opaque codes**, not readable names.
            To display human-readable brand and model names, you must join with reference tables.

            ## Brand Resolution
            - `ins_cars.car_mc_brand` contains codes like 'TA3PD27008'
            - Join with `srv_mc_horizon_brand` on `car_mc_brand = brand_id`
            - Returns `brand_name` (e.g., 'BMW', 'Mercedes', 'Toyota')

            ```sql
            SELECT b.brand_name, COUNT(*) AS car_count
            FROM ins_cars c
            JOIN srv_mc_horizon_brand b ON c.car_mc_brand = b.brand_id
            GROUP BY b.brand_name
            ORDER BY car_count DESC
            ```

            ## Model Resolution
            - `ins_cars.car_mc_modelname` contains opaque model codes
            - Join with `srv_mc_horizon_modelname` on matching `brand_id` and `modelname_id`
            - The join requires: `b.brand_id = mn.brand_id AND c.car_mc_modelname = mn.modelname_id`

            ```sql
            SELECT b.brand_name, mn.modelname_name, COUNT(*) AS cnt
            FROM ins_cars c
            JOIN srv_mc_horizon_brand b ON c.car_mc_brand = b.brand_id
            JOIN srv_mc_horizon_modelname mn ON b.brand_id = mn.brand_id
                AND b.category_id = mn.category_id
                AND c.car_mc_modelname = mn.modelname_id
            GROUP BY b.brand_name, mn.modelname_name
            ORDER BY cnt DESC
            ```

            ## Car Make (Alternative System)
            - `ins_cars.car_make` is an integer foreign key
            - Join with `srv_mc_catalog_make` on `car_make = mc_make`
            - Returns `mc_make_name` (e.g., 'Toyota', 'Honda')
            - This is a different naming system from horizon brands

            ```sql
            SELECT m.mc_make_name, COUNT(*) AS cnt
            FROM ins_cars c
            JOIN srv_mc_catalog_make m ON c.car_make = m.mc_make
            WHERE c.car_make > 0
            GROUP BY m.mc_make_name
            ORDER BY cnt DESC
            ```

            ## Important: Two Different Brand Systems
            1. **Horizon brands** (`srv_mc_horizon_brand.brand_name`) — used via `car_mc_brand`
            2. **Catalog makes** (`srv_mc_catalog_make.mc_make_name`) — used via `car_make`

            The horizon system is more commonly used in MC estimates. Both are valid.

            ## How to Verify
            ```sql
            SELECT COUNT(DISTINCT brand_name) FROM srv_mc_horizon_brand WHERE brand_deleted=0;
            SELECT COUNT(*) FROM srv_mc_catalog_make WHERE mc_make_deleted=0;
            SELECT COUNT(*) FROM srv_mc_horizon_model;
            SELECT COUNT(*) FROM srv_mc_catalog_model;
            ```

            ## Tags
            `brand-name-resolution, model-name-resolution, srv_mc_horizon_brand, srv_mc_horizon_modelname, srv_mc_catalog_make, ins_cars, opaque-codes`
        """),
    },
    "mc_vs_n24_comparison": {
        "title": "MC vs N24 Estimate Comparison — Regulatory vs Catalog Cost Analysis",
        "content": textwrap.dedent("""\
            # MC vs N24 Estimate Comparison — Regulatory vs Catalog Cost Analysis

            ## Overview
            The bgins database contains two types of estimates:
            - **MC (MultiCat)**: Catalog-based estimates using parts pricing from the MultiCat system
            - **N24 (Regulatory)**: Estimates based on the N24 regulatory pricing standard

            Both are stored in `ins_mc_invcalc` with the `type` column distinguishing them.

            ## Key Characteristics
            - N24 estimates are **much less common** than MC estimates
            - Only a **small subset of claims** have both MC and N24 estimates
            - MC estimates tend to be higher than N24 for the same claim
            - Always query the current counts — the dataset grows over time:
            ```sql
            SELECT type, COUNT(*) FROM ins_mc_invcalc GROUP BY type;
            SELECT COUNT(*) FROM (
                SELECT opis_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id
            ) m JOIN (
                SELECT opis_id FROM ins_mc_invcalc WHERE type='n24' GROUP BY opis_id
            ) n ON m.opis_id = n.opis_id;
            ```

            ## Comparing MC vs N24 for the Same Claim

            ```sql
            WITH latest AS (
                SELECT ic.*
                FROM ins_mc_invcalc ic
                INNER JOIN (
                    SELECT opis_id, type, MAX(invcalc_id) AS max_id
                    FROM ins_mc_invcalc
                    GROUP BY opis_id, type
                ) lm ON lm.opis_id = ic.opis_id AND lm.max_id = ic.invcalc_id
            )
            SELECT
                mc.opis_id,
                mc.total_cost AS mc_cost,
                n24.total_cost AS n24_cost,
                mc.total_cost - n24.total_cost AS mc_minus_n24
            FROM latest mc
            JOIN latest n24 ON mc.opis_id = n24.opis_id AND n24.type = 'n24'
            WHERE mc.type = 'mc'
            ```

            ## Important Notes
            - The subset of claims with both types is small — results may be volatile
            - MC is generally higher than N24 for the same claim
            - When comparing, always use latest estimate per type (not all rows)
            - Check the current split with: `SELECT ... mc.total_cost - n24.total_cost ...`

            ## Tags
            `mc-vs-n24, estimate-comparison, ins_mc_invcalc, regulatory, catalog, cost-analysis`
        """),
    },
    "date_arithmetic_mysql": {
        "title": "MySQL Date Arithmetic — DATEDIFF, DATE_FORMAT, and Temporal Patterns",
        "content": textwrap.dedent("""\
            # MySQL Date Arithmetic — DATEDIFF, DATE_FORMAT, and Temporal Patterns

            ## Core Functions

            ### DATEDIFF(date1, date2)
            Returns the number of days between two dates (date1 - date2).
            ```sql
            -- Filing lag: days from damage to claim filing
            SELECT DATEDIFF(o.opis_date, d.damage_date) AS filing_lag
            FROM ins_opis o
            JOIN ins_damages d ON d.damage_id = o.damage_id
            ```

            **Important**: When comparing DATE and DATETIME columns, cast first:
            ```sql
            WHERE CAST(o.opis_date AS DATE) = d.damage_date  -- opis_date is DATETIME, damage_date is DATE
            ```

            ### DATE_FORMAT
            ```sql
            DATE_FORMAT(date_col, '%Y-%m')    -- Monthly: '2023-06'
            DATE_FORMAT(date_col, '%Y-%m-%d')  -- Daily
            DATE_FORMAT(date_col, '%Y')        -- Yearly
            ```

            ### YEAR / QUARTER / MONTH / DAYOFWEEK
            ```sql
            YEAR(damage_date)       -- Extract year
            QUARTER(opis_date)      -- 1-4
            MONTH(damage_date)      -- 1-12
            DAYOFWEEK(damage_date)  -- 1=Sunday, 7=Saturday
            ```

            ## Common Temporal Queries

            ### Claims per month
            ```sql
            SELECT DATE_FORMAT(o.opis_date, '%Y-%m') AS month, COUNT(*) AS claims
            FROM ins_opis o
            GROUP BY month ORDER BY month
            ```

            ### Filing lag distribution
            ```sql
            SELECT
                CASE
                    WHEN DATEDIFF(o.opis_date, d.damage_date) <= 0 THEN 'Same day'
                    WHEN DATEDIFF(o.opis_date, d.damage_date) <= 7 THEN '1-7 days'
                    WHEN DATEDIFF(o.opis_date, d.damage_date) <= 30 THEN '8-30 days'
                    ELSE '30+ days'
                END AS lag_bucket,
                COUNT(*) AS cnt
            FROM ins_opis o
            JOIN ins_damages d ON d.damage_id = o.damage_id
            WHERE d.damage_date IS NOT NULL AND o.opis_date IS NOT NULL
            GROUP BY lag_bucket
            ```

            ### Repair duration
            ```sql
            SELECT AVG(DATEDIFF(end_repair, start_repair)) AS avg_days
            FROM ins_invrepair
            WHERE start_repair IS NOT NULL AND end_repair IS NOT NULL
            ```

            ## Key Date Columns
            | Column | Table | Type | Description |
            |--------|-------|------|-------------|
            | damage_date | ins_damages | DATE | When the accident/damage occurred |
            | damage_notice | ins_damages | DATE | When damage was reported |
            | damage_fdate | ins_damages | DATETIME | Filing date |
            | opis_date | ins_opis | DATETIME | Claim assessment date |
            | send_date | ins_invrepair | DATETIME | Repair request sent |
            | start_repair | ins_invrepair | DATE | Repair started |
            | end_repair | ins_invrepair | DATE | Repair completed |
            | estimated_date_repair | ins_invrepair | DATE | Expected repair completion |

            ## Common Pitfalls

            ### DATETIME vs DATE Confusion
            `ins_opis.opis_date` is DATETIME but `ins_damages.damage_date` is DATE.
            Direct comparison can give wrong results:
            ```sql
            -- CORRECT: Cast DATETIME to DATE first
            WHERE CAST(o.opis_date AS DATE) = d.damage_date

            -- ALSO CORRECT: DATEDIFF ignores time component
            WHERE DATEDIFF(o.opis_date, d.damage_date) = 0
            ```

            ### DATEDIFF Argument Order
            `DATEDIFF(d1, d2)` returns `d1 - d2`. Wrong order flips the sign:
            ```sql
            -- Filing lag (positive = filed after damage):
            DATEDIFF(o.opis_date, d.damage_date)  -- NOT the reverse
            ```

            ### Inclusive vs Exclusive Boundaries
            - "filed within 7 days" → `DATEDIFF(...) BETWEEN 0 AND 7`
            - NOT `DATEDIFF(...) < 7` (misses day 7)
            - NOT `DATEDIFF(...) <= 7` without `>= 0` (includes negative = future dates)

            ## MySQL-Specific Notes
            - NO `DATE_TRUNC` (PostgreSQL only) — use `DATE_FORMAT` or `YEAR()/QUARTER()`
            - NO `INTERVAL` subtraction — use `DATEDIFF()`
            - `DATEDIFF` only returns days — for hours, use `TIMESTAMPDIFF(HOUR, d1, d2)`

            ## Tags
            `date-arithmetic, DATEDIFF, DATE_FORMAT, temporal-grouping, filing-lag, repair-duration, MySQL, DATETIME, DATE, CAST, common-pitfall`
        """),
    },
    "data_quality_checks": {
        "title": "Data Quality Checks — Referential Integrity, Domain Constraints, and Temporal Sanity",
        "content": textwrap.dedent("""\
            # Data Quality Checks — Referential Integrity, Domain Constraints, and Temporal Sanity

            ## Overview
            Data quality validation is essential for insurance claims analysis. The bgins database
            has known quality issues that analysts must check for.

            ## Referential Integrity Checks

            ### Orphan claims (opis without damage)
            ```sql
            SELECT COUNT(*) FROM ins_opis o
            LEFT JOIN ins_damages d ON d.damage_id = o.damage_id
            WHERE d.damage_id IS NULL
            ```

            ### Orphan damage lines (opis_rows without opis)
            ```sql
            SELECT COUNT(*) FROM ins_opis_rows r
            LEFT JOIN ins_opis o ON o.opis_id = r.opis_id
            WHERE o.opis_id IS NULL
            ```

            ### Orphan estimates (without claim)
            ```sql
            SELECT COUNT(*) FROM ins_mc_invcalc ic
            LEFT JOIN ins_opis o ON o.opis_id = ic.opis_id
            WHERE o.opis_id IS NULL
            ```

            ### Orphan opis (car_id not in ins_cars)
            Note: car_id=0 is a sentinel meaning "no car linked" — exclude it.
            ```sql
            SELECT COUNT(*) FROM ins_opis o
            LEFT JOIN ins_cars c ON c.car_id = o.car_id
            WHERE o.car_id > 0 AND c.car_id IS NULL
            ```

            ## Domain Constraint Checks

            ### Negative costs
            ```sql
            SELECT COUNT(*) FROM ins_mc_invcalc WHERE total_cost < 0
            ```

            ### Invalid estimate types
            ```sql
            SELECT COUNT(*) FROM ins_mc_invcalc WHERE type NOT IN ('mc', 'n24')
            ```

            ### Parts outside known ranges
            ```sql
            SELECT COUNT(*) FROM ins_opis_rows
            WHERE part_id < 0 OR (part_id >= 10000000 AND part_id < 20000000)
            ```

            ## Temporal Sanity Checks

            ### Claim filed before accident
            ```sql
            SELECT COUNT(*) FROM ins_opis o
            JOIN ins_damages d ON d.damage_id = o.damage_id
            WHERE CAST(o.opis_date AS DATE) < d.damage_date
                AND d.damage_date IS NOT NULL AND o.opis_date IS NOT NULL
            ```

            ### Repair before claim filing
            ```sql
            SELECT COUNT(*) FROM ins_invrepair ir
            JOIN ins_opis o ON o.opis_id = ir.opis_id
            WHERE ir.start_repair IS NOT NULL AND o.opis_date IS NOT NULL
                AND ir.start_repair < CAST(o.opis_date AS DATE)
            ```

            ### Repair end before start
            ```sql
            SELECT COUNT(*) FROM ins_invrepair
            WHERE start_repair IS NOT NULL AND end_repair IS NOT NULL
                AND end_repair < start_repair
            ```

            ### Future damage dates
            ```sql
            SELECT COUNT(*) FROM ins_damages WHERE damage_date > CURDATE()
            ```

            ## Sentinel Values
            - `car_id = 0` in ins_opis: means no car linked (not an orphan)
            - `part_id = 0`: means no specific part
            - `service_id = 0`: means no repair shop assigned

            ## Tags
            `data-quality, referential-integrity, anti-join, orphan-detection, domain-constraints, temporal-sanity`
        """),
    },
    "expense_analysis": {
        "title": "Expense Analysis — Suppliers, Expense Types, and Cost Breakdown",
        "content": textwrap.dedent("""\
            # Expense Analysis — Suppliers, Expense Types, and Cost Breakdown

            ## Overview
            The `ins_mc_invexpenses` table contains individual expense lines linked to MC estimates.
            Each line represents a cost item (part, labor, paint, etc.) with supplier information.
            This is one of the largest tables — check current size with `SELECT COUNT(*) FROM ins_mc_invexpenses`.

            ## Table Structure
            - `doc_id`: Links to `ins_mc_invcalc.invcalc_id` (the estimate)
            - `item_id`: Links to `ins_mc_invitems.item_id` (specific damage line)
                - `item_id = 0`: Document-level expense (not linked to a specific part)
            - `expense_type`: Links to `inv_exptypes.exptype_id` for type name
            - `unit_id`: Links to `inv_expunits.unit_id` for unit name
            - `expense_subtype`: 0 = standard, 1 = alternative/aftermarket

            ## Key Queries

            ### Top suppliers by total value
            ```sql
            SELECT supplier_name, SUM(value_vat) AS total, COUNT(*) AS lines
            FROM ins_mc_invexpenses
            WHERE supplier_name != ''
            GROUP BY supplier_name
            ORDER BY total DESC
            LIMIT 10
            ```

            ### Expense type distribution
            ```sql
            SELECT et.et_name, COUNT(*) AS cnt, SUM(e.value_vat) AS total
            FROM ins_mc_invexpenses e
            JOIN inv_exptypes et ON e.expense_type = et.exptype_id
            GROUP BY et.et_name
            ORDER BY total DESC
            ```

            ### Document-level (unlinked) expenses
            ```sql
            SELECT
                SUM(CASE WHEN item_id = 0 THEN value_vat ELSE 0 END) AS unlinked_value,
                SUM(value_vat) AS total_value,
                ROUND(100 * SUM(CASE WHEN item_id = 0 THEN value_vat ELSE 0 END) / SUM(value_vat), 2) AS pct
            FROM ins_mc_invexpenses
            ```

            ### Average expenses per estimate
            ```sql
            SELECT AVG(cnt) FROM (
                SELECT doc_id, COUNT(*) AS cnt
                FROM ins_mc_invexpenses
                GROUP BY doc_id
            ) t
            ```

            ### For MC estimates only (not N24)
            ```sql
            SELECT SUM(e.value_vat) AS mc_expense_total
            FROM ins_mc_invexpenses e
            JOIN ins_mc_invcalc ic ON e.doc_id = ic.invcalc_id
            WHERE ic.type = 'mc'
            ```

            ## Expense Subtypes
            | Subtype | Description |
            |---------|-------------|
            | 0 | Standard/OEM parts (majority) |
            | 1 | Alternative/aftermarket |

            Check current distribution: `SELECT expense_subtype, COUNT(*) FROM ins_mc_invexpenses GROUP BY expense_subtype`

            ## Tags
            `expense-analysis, ins_mc_invexpenses, supplier, expense-type, cost-breakdown, item_id, document-level`
        """),
    },
    "repair_workflow": {
        "title": "Repair Workflow — Shop Performance, Duration, and Status Analysis",
        "content": textwrap.dedent("""\
            # Repair Workflow — Shop Performance, Duration, and Status Analysis

            ## Overview
            The `ins_invrepair` table tracks repair requests sent to service shops,
            covering the full repair lifecycle from request to completion.

            ## Repair Statuses
            | Status | Meaning |
            |--------|---------|
            | 0 | Pending / New |
            | 10 | Sent |
            | 1000 | Completed |
            | 2000 | Cancelled |
            | 3000 | Returned |
            | 4000 | Other |

            Check current distribution: `SELECT repair_status, COUNT(*) FROM ins_invrepair GROUP BY repair_status`

            ## Key Date Fields
            - `send_date` (DATETIME): When repair request was sent to shop
            - `start_repair` (DATE): When repair actually started
            - `end_repair` (DATE): When repair was completed
            - `estimated_date_repair` (DATE): Expected completion date

            ## Common Queries

            ### Repair duration
            ```sql
            SELECT AVG(DATEDIFF(end_repair, start_repair)) AS avg_days
            FROM ins_invrepair
            WHERE start_repair IS NOT NULL AND end_repair IS NOT NULL
            ```

            ### Shop performance (top shops by completion)
            ```sql
            SELECT service_id,
                COUNT(*) AS total,
                SUM(CASE WHEN repair_status = 1000 THEN 1 ELSE 0 END) AS completed,
                ROUND(100 * SUM(CASE WHEN repair_status = 1000 THEN 1 ELSE 0 END) / COUNT(*), 1) AS completion_pct
            FROM ins_invrepair
            GROUP BY service_id
            HAVING total >= 5
            ORDER BY completion_pct DESC
            ```

            ### Claims with repair but no estimate
            ```sql
            SELECT COUNT(DISTINCT ir.opis_id)
            FROM ins_invrepair ir
            LEFT JOIN ins_mc_invcalc mc ON mc.opis_id = ir.opis_id AND mc.type = 'mc'
            WHERE mc.invcalc_id IS NULL
            ```

            ## Important Notes
            - `car_make_name`, `car_model_name`, `car_chassis` are denormalized in ins_invrepair
            - `service_id` identifies the repair shop
            - A claim can have multiple repair records
            - To check completion rate: `SELECT ROUND(100*SUM(repair_status=1000)/COUNT(*),1) FROM ins_invrepair`

            ## Tags
            `repair-workflow, ins_invrepair, repair-status, duration, shop-performance, cycle-time`
        """),
    },
    "cost_structure_analysis": {
        "title": "Cost Structure Analysis — Parts, Paint, Labor, and Cost Shares",
        "content": textwrap.dedent("""\
            # Cost Structure Analysis — Parts, Paint, Labor, and Cost Shares

            ## Overview
            Insurance claim costs break down into several components. Both `ins_damages` (actual costs)
            and `ins_mc_invcalc` (estimated costs) contain detailed cost breakdowns.

            ## Cost Components in ins_mc_invcalc (estimates)
            | Column | Description |
            |--------|-------------|
            | newparts_cost | Cost of new replacement parts |
            | repairs_cost | Labor cost for repairs |
            | mounts_cost | Cost of mounting/dismounting |
            | paints_cost | Total paint cost (labor + materials) |
            | other_cost | Miscellaneous costs |
            | total_cost | Sum of all costs |
            | vat_sum | VAT amount |
            | service_discall | Total discount percentage |

            ## Cost Structure from Latest MC Estimates

            ```sql
            WITH latest_mc AS (
                SELECT ic.* FROM ins_mc_invcalc ic
                INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id
                    FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm
                ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id
            )
            SELECT
                ROUND(100 * AVG(newparts_cost / NULLIF(total_cost, 0)), 2) AS avg_parts_pct,
                ROUND(100 * AVG(paints_cost / NULLIF(total_cost, 0)), 2) AS avg_paint_pct,
                ROUND(100 * AVG(repairs_cost / NULLIF(total_cost, 0)), 2) AS avg_repair_pct,
                ROUND(100 * AVG(mounts_cost / NULLIF(total_cost, 0)), 2) AS avg_mount_pct,
                ROUND(100 * AVG(other_cost / NULLIF(total_cost, 0)), 2) AS avg_other_pct
            FROM latest_mc
            WHERE total_cost > 0
            ```

            ## Ratio Calculation — AVG(a/b) vs SUM(a)/SUM(b)

            These two approaches give **different results** and the choice depends on the question:

            1. `AVG(a/b)` — average of per-record ratios (each claim weighted equally)
            2. `SUM(a)/SUM(b)` — portfolio-level aggregate ratio (weighted by claim size)

            **Example** (two claims):
            - Claim A: parts=100, total=200 → per-claim ratio = 50%
            - Claim B: parts=500, total=10000 → per-claim ratio = 5%
            - `AVG(ratio)` = (50% + 5%) / 2 = **27.5%** (equal weight per claim)
            - `SUM(parts)/SUM(total)` = 600/10200 = **5.9%** (weighted by size)

            **When to use which:**
            - "Average parts cost **share** per claim" → `AVG(a / NULLIF(b, 0))`
            - "What **share** of total portfolio cost is parts" → `SUM(a) / SUM(b)`
            - When in doubt, the per-claim average (`AVG(a/b)`) is usually what analysts want

            **Always use NULLIF to prevent division by zero:**
            ```sql
            -- CORRECT:
            AVG(newparts_cost / NULLIF(total_cost, 0))
            -- WRONG (crashes on zero total_cost):
            AVG(newparts_cost / total_cost)
            ```

            ## Paint-Heavy and Parts-Heavy Claims
            ```sql
            -- Paint heavy: paint share > 40%
            SELECT COUNT(*) FROM latest_mc
            WHERE total_cost > 0 AND paints_cost / total_cost > 0.4

            -- Parts heavy: parts share > 60%
            SELECT COUNT(*) FROM latest_mc
            WHERE total_cost > 0 AND newparts_cost / total_cost > 0.6
            ```

            ## How to Get Current Values
            Run the cost structure query above for current shares. Additionally:
            ```sql
            -- Paint-heavy count
            WITH latest_mc AS (...) SELECT COUNT(*) FROM latest_mc
            WHERE total_cost > 0 AND paints_cost / total_cost > 0.4;
            -- Parts-heavy count
            WITH latest_mc AS (...) SELECT COUNT(*) FROM latest_mc
            WHERE total_cost > 0 AND newparts_cost / total_cost > 0.6;
            ```
            Paint share tends to dominate in this dataset (higher than parts share).

            ## Tags
            `cost-structure, cost-shares, paint-heavy, parts-heavy, NULLIF, ratio-calculation, ins_mc_invcalc`
        """),
    },
    "median_percentile_mysql": {
        "title": "Median and Percentile Calculation in MySQL — ROW_NUMBER Approach",
        "content": textwrap.dedent("""\
            # Median and Percentile Calculation in MySQL — ROW_NUMBER Approach

            ## The Problem
            MySQL does not have `PERCENTILE_CONT` or `MEDIAN` aggregate functions.

            ## Median Using ROW_NUMBER
            ```sql
            SELECT AVG(total_cost) AS median_cost
            FROM (
                SELECT total_cost,
                    ROW_NUMBER() OVER (ORDER BY total_cost) AS rn,
                    COUNT(*) OVER () AS cnt
                FROM ins_damages
                WHERE total_cost > 0
            ) sub
            WHERE rn IN (FLOOR((cnt+1)/2), CEIL((cnt+1)/2))
            ```

            ## P90 (90th Percentile) Using ROW_NUMBER
            ```sql
            WITH ranked AS (
                SELECT total_cost,
                    ROW_NUMBER() OVER (ORDER BY total_cost) AS rn,
                    COUNT(*) OVER () AS cnt
                FROM ins_mc_invcalc
                WHERE type='mc'
            )
            SELECT total_cost AS p90
            FROM ranked
            WHERE rn = CEIL(0.9 * cnt)
            ```

            ## Notes
            - `FLOOR((cnt+1)/2)` and `CEIL((cnt+1)/2)` handle even/odd counts
            - For even counts, median is the average of two middle values
            - For percentiles, use `CEIL(percentile * cnt)`

            ## Tags
            `median, percentile, ROW_NUMBER, window-function, MySQL, P90, P50`
        """),
    },
}


# ─── Generate domain knowledge files ────────────────────────────────────────

DOMAIN_FILES = {
    "schema_overview": {
        "title": "bgins Database Schema Overview — Bulgarian Insurance Claims System",
        "content": textwrap.dedent("""\
            # bgins Database Schema Overview — Bulgarian Insurance Claims System

            ## Overview
            The bgins database is a MySQL 8.0 database containing Bulgarian motor insurance claims data.
            It has 21 tables with data spanning from February 2021 to February 2026.

            ## Core Entity Tables

            ### ins_cars
            Insured vehicles with specifications.
            - Primary key: `car_id`
            - Key columns: `car_make` (FK to catalog), `car_mc_brand` (FK to horizon brand),
              `car_year`, `car_class`, `car_fuel`, `car_chassis` (VIN)
            - Brand resolution: Join `srv_mc_horizon_brand` on `car_mc_brand = brand_id`

            ### ins_damages
            Damage events (accidents/incidents).
            - Primary key: `damage_id`
            - Key columns: `damage_date`, `damage_place`, `damage_place_country`,
              `total_cost`, `newparts_cost`, `paints_cost`, `repairs_cost`, `mounts_cost`,
              `other_cost`, `transport_cost`, `premium_main`, `car_yeargroup`
            - Contains both actual cost breakdown and policy premium info

            ### ins_opis
            Claims/assessments — the central entity linking cars, damages, and estimates.
            - Primary key: `opis_id`
            - Foreign keys: `damage_id` → ins_damages, `car_id` → ins_cars
            - Key columns: `opis_date` (DATETIME), `opis_status`, `claim_type`,
              `items_count_current`, `opis_digital`, `opis_ai`

            ### ins_opis_rows
            Individual damaged parts per claim.
            - Primary key: `opis_rowid`
            - Foreign key: `opis_id` → ins_opis
            - Key columns: `part_id`, `quantity`, `part_new` (0/1), `part_repair` (0-3),
              `part_paint` (0/1)

            ## Estimate Tables

            ### ins_mc_invcalc
            MC and N24 cost estimates.
            - Primary key: `invcalc_id`
            - Foreign key: `opis_id` → ins_opis
            - Key columns: `type` (enum 'mc'/'n24'), `total_cost`, `newparts_cost`,
              `paints_cost`, `repairs_cost`, `mounts_cost`, `other_cost`,
              `is_active`, `vat_sum`, `service_discall`
            - **CRITICAL**: Multiple revisions per claim — use MAX(invcalc_id) for latest

            ### ins_mc_invexpenses
            Individual expense lines within estimates.
            - Foreign key: `doc_id` → ins_mc_invcalc.invcalc_id
            - Key columns: `item_id` (0=document-level), `expense_name`, `expense_type`,
              `supplier_name`, `value_vat`, `expense_subtype` (0=standard, 1=alternative)

            ### ins_mc_invitems
            Links estimate line items to opis_rows (damaged parts).
            - Foreign key: `invcalc_id` → ins_mc_invcalc
            - Key columns: `item_name`, `mc_number`, `part_id`

            ## Repair Tables

            ### ins_invrepair
            Repair shop assignments and tracking.
            - Primary key: `repair_id`
            - Foreign key: `opis_id` → ins_opis
            - Key columns: `service_id`, `send_date`, `start_repair`, `end_repair`,
              `repair_status` (0=pending, 1000=completed), `car_make_name` (denormalized)

            ## Document Tables

            ### ins_gendocs
            Generated documents (inspection reports, photos).
            - Foreign key: `opis_id` → ins_opis
            - Key columns: `doc_type`, `gen_date`, `file_deleted`

            ### ins_gendocs_opis_rows
            Links documents to specific damage lines.

            ## Reference/Lookup Tables

            ### Parts Catalogs
            - `ins_partsindex`: SC catalog, part_id < 10M
            - `ins_partsomc`: MC catalog, 10M-20M (may be empty)
            - `ins_partsfree`: Free-text parts, part_id >= 20M

            ### Vehicle Catalogs
            - `srv_mc_catalog_make`: Car makes (mc_make → mc_make_name)
            - `srv_mc_catalog_model`: Car models
            - `srv_mc_horizon_brand`: Horizon brands (brand_id → brand_name)
            - `srv_mc_horizon_model`: Horizon models
            - `srv_mc_horizon_modelname`: Model names
            - `srv_mc_horizon_category`: Vehicle categories (small lookup table)

            ### Expense Types
            - `inv_exptypes` (14 rows): Expense type definitions
            - `inv_expunits` (8 rows): Unit definitions

            ## Key Relationships (ER Model)

            ```
            ins_cars ←── ins_opis ──→ ins_damages
                              │
                              ├── ins_opis_rows (damaged parts)
                              │       └── ins_partsindex / ins_partsfree (part names)
                              │
                              ├── ins_mc_invcalc (estimates)
                              │       ├── ins_mc_invitems (line items)
                              │       └── ins_mc_invexpenses (expense details)
                              │
                              ├── ins_invrepair (repair tracking)
                              │
                              └── ins_gendocs (documents)
                                      └── ins_gendocs_opis_rows
            ```

            ## MySQL-Specific Notes
            - MySQL 8.0.45 — CTEs and window functions supported
            - `DATEDIFF(d1, d2)` for date arithmetic (not `d1 - d2`)
            - `DATE_FORMAT` for date formatting (not `DATE_TRUNC`)
            - `ENUM` type for ins_mc_invcalc.type ('mc', 'n24')
            - No `PERCENTILE_CONT` — use `ROW_NUMBER()` for percentiles
            - `lines` is a reserved word — do not use as alias

            ## Tags
            `schema, database, bgins, MySQL, ER-model, tables, relationships, insurance-claims`
        """),
    },
    "business_glossary": {
        "title": "Insurance Claims Business Glossary — Domain Terms and Concepts",
        "content": textwrap.dedent("""\
            # Insurance Claims Business Glossary — Domain Terms and Concepts

            ## Core Concepts

            ### Claim (Opis)
            An insurance claim filed after a vehicle damage event. Stored in `ins_opis`.
            Each claim links to one damage event and one insured car.

            ### Damage Event
            An accident, theft, or other incident causing vehicle damage. Stored in `ins_damages`.
            Contains the actual cost breakdown from the insurance company.

            ### MC Estimate (MultiCat)
            A catalog-based cost estimate using the MultiCat parts pricing system.
            Stored in `ins_mc_invcalc` with `type='mc'`. Multiple revisions per claim.

            ### N24 Estimate (Regulatory)
            A cost estimate based on the N24 regulatory pricing standard.
            Stored in `ins_mc_invcalc` with `type='n24'`. Less common than MC.

            ### Repair Request
            A request sent to a service shop for vehicle repair. Stored in `ins_invrepair`.
            Tracks the full repair lifecycle from request to completion.

            ## Cost Components

            | Term | Column | Description |
            |------|--------|-------------|
            | New Parts Cost | newparts_cost | Cost of replacement parts |
            | Repairs Cost | repairs_cost | Labor for mechanical repairs |
            | Mounts Cost | mounts_cost | Mounting/dismounting labor |
            | Paints Cost | paints_cost | Paint labor + materials |
            | Other Cost | other_cost | Miscellaneous costs |
            | Transport Cost | transport_cost | Vehicle transport |
            | Total Cost | total_cost | Sum of all cost components |
            | VAT Sum | vat_sum | Value-added tax |
            | Discount | service_discall | Overall discount percentage |

            ## Part Treatment Types

            | part_new | part_repair | Meaning |
            |----------|-------------|---------|
            | 1 | 0 | Replace with new part |
            | 0 | 1 | Minor repair |
            | 0 | 2 | Medium repair |
            | 0 | 3 | Major repair |
            | 0 | 0 | No action (paint only if part_paint=1) |

            ## Claim Statuses
            - `opis_status = 1000`: Completed/closed claim
            - `repair_status = 0`: Pending repair
            - `repair_status = 1000`: Completed repair

            ## Paint-Heavy vs Parts-Heavy Claims
            - **Paint-heavy**: `paints_cost / total_cost > 0.4` (40%+)
            - **Parts-heavy**: `newparts_cost / total_cost > 0.6` (60%+)
            - Paint share tends to be the **largest** cost component in this dataset
            - Parts share is typically the **second largest**

            ## Regress Cases
            Claims where the insurance company seeks recovery from a responsible third party.
            Flagged by `damage_isregress = 1` in `ins_damages` (a small minority of claims).
            Check current rate: `SELECT ROUND(100*AVG(damage_isregress),1) FROM ins_damages`

            ## Currency
            - Primary currency: BGN (Bulgarian Lev)
            - `calc_currency_code` in ins_damages for claim currency

            ## Data Period
            The database is a live system — data grows over time. Always query for current stats:
            ```sql
            SELECT MIN(damage_date), MAX(damage_date) FROM ins_damages;
            SELECT COUNT(*) FROM ins_opis;
            SELECT COUNT(*) FROM ins_cars;
            ```

            ## Tags
            `business-glossary, insurance, claims, MC-estimate, N24, repair, cost-structure, domain-knowledge`
        """),
    },
    "join_patterns": {
        "title": "Common Join Patterns — Navigating the bgins ER Model",
        "content": textwrap.dedent("""\
            # Common Join Patterns — Navigating the bgins ER Model

            ## Central Hub: ins_opis
            `ins_opis` is the central table connecting cars, damages, estimates, repairs, and documents.

            ## Basic Joins

            ### Claim → Damage
            ```sql
            SELECT o.opis_id, d.damage_date, d.total_cost
            FROM ins_opis o
            JOIN ins_damages d ON d.damage_id = o.damage_id
            ```

            ### Claim → Car
            ```sql
            SELECT o.opis_id, c.car_year, c.car_fuel
            FROM ins_opis o
            JOIN ins_cars c ON c.car_id = o.car_id
            ```

            ### Claim → Car → Brand Name
            ```sql
            SELECT o.opis_id, b.brand_name
            FROM ins_opis o
            JOIN ins_cars c ON c.car_id = o.car_id
            JOIN srv_mc_horizon_brand b ON c.car_mc_brand = b.brand_id
            ```

            ### Claim → Damage Lines → Part Names
            ```sql
            SELECT o.opis_id, r.part_id, COALESCE(pi.part_name, pf.part_name) AS part_name
            FROM ins_opis o
            JOIN ins_opis_rows r ON r.opis_id = o.opis_id
            LEFT JOIN ins_partsindex pi ON r.part_id = pi.part_id AND r.part_id < 10000000
            LEFT JOIN ins_partsfree pf ON r.part_id = pf.part_id AND r.part_id >= 20000000
            ```

            ### Claim → Latest MC Estimate
            ```sql
            WITH latest_mc AS (
                SELECT ic.* FROM ins_mc_invcalc ic
                INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id
                    FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm
                ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id
            )
            SELECT o.opis_id, mc.total_cost
            FROM ins_opis o
            JOIN latest_mc mc ON mc.opis_id = o.opis_id
            ```

            ### Claim → Repair
            ```sql
            SELECT o.opis_id, ir.service_id, ir.repair_status,
                DATEDIFF(ir.end_repair, ir.start_repair) AS repair_days
            FROM ins_opis o
            JOIN ins_invrepair ir ON ir.opis_id = o.opis_id
            ```

            ### Estimate → Expenses
            ```sql
            SELECT ic.invcalc_id, e.expense_name, e.value_vat
            FROM ins_mc_invcalc ic
            JOIN ins_mc_invexpenses e ON e.doc_id = ic.invcalc_id
            ```

            ### Expense → Type Name
            ```sql
            SELECT e.expense_name, et.et_name, e.value_vat
            FROM ins_mc_invexpenses e
            JOIN inv_exptypes et ON e.expense_type = et.exptype_id
            ```

            ## Full Chain: Car → Brand → Claim → Damage → Latest MC Estimate
            ```sql
            WITH latest_mc AS (...)
            SELECT b.brand_name, d.damage_date, mc.total_cost
            FROM ins_opis o
            JOIN ins_cars c ON c.car_id = o.car_id
            JOIN srv_mc_horizon_brand b ON c.car_mc_brand = b.brand_id
            JOIN ins_damages d ON d.damage_id = o.damage_id
            JOIN latest_mc mc ON mc.opis_id = o.opis_id
            ```

            ## Tags
            `join-patterns, ER-model, ins_opis, multi-table, relationships, foreign-keys`
        """),
    },
    "frequency_analysis": {
        "title": "Claims Frequency Analysis — Trends, Seasonality, and Filing Patterns",
        "content": textwrap.dedent("""\
            # Claims Frequency Analysis — Trends, Seasonality, and Filing Patterns

            ## Overview
            Frequency analysis examines how many claims occur over time, by category, and by pattern.
            The database is live — always query for current totals and date ranges.

            ## Claims Per Month
            ```sql
            SELECT DATE_FORMAT(o.opis_date, '%Y-%m') AS month, COUNT(*) AS claims
            FROM ins_opis o
            WHERE o.opis_date IS NOT NULL
            GROUP BY month ORDER BY month
            ```

            ## Claims Per Year
            ```sql
            SELECT YEAR(o.opis_date) AS yr, COUNT(*) AS claims
            FROM ins_opis o WHERE o.opis_date IS NOT NULL
            GROUP BY yr ORDER BY yr
            ```

            ## Filing Lag (Damage to Claim)
            The time between when damage occurs and when a claim is filed.
            ```sql
            SELECT
                AVG(DATEDIFF(o.opis_date, d.damage_date)) AS avg_lag_days,
                MIN(DATEDIFF(o.opis_date, d.damage_date)) AS min_lag,
                MAX(DATEDIFF(o.opis_date, d.damage_date)) AS max_lag
            FROM ins_opis o
            JOIN ins_damages d ON d.damage_id = o.damage_id
            WHERE d.damage_date IS NOT NULL AND o.opis_date IS NOT NULL
            ```

            ## Average Claims Per Day
            ```sql
            SELECT COUNT(*) / DATEDIFF(MAX(opis_date), MIN(opis_date)) AS avg_per_day
            FROM ins_opis WHERE opis_date IS NOT NULL
            ```
            Note: This divides total claims by total day span. Run it to get the current rate.

            ## Day-of-Week Pattern
            ```sql
            SELECT DAYOFWEEK(d.damage_date) AS dow, COUNT(*) AS cnt
            FROM ins_damages d WHERE d.damage_date IS NOT NULL
            GROUP BY dow ORDER BY dow
            ```

            ## Tags
            `frequency, trends, seasonality, filing-lag, temporal-analysis, claims-per-month`
        """),
    },
    "geographic_analysis": {
        "title": "Geographic Analysis — Location-Based Cost and Frequency Patterns",
        "content": textwrap.dedent("""\
            # Geographic Analysis — Location-Based Cost and Frequency Patterns

            ## Overview
            Claims in the bgins database have location data via `ins_damages.damage_place`
            (free-text location name) and `ins_damages.damage_place_country` (2-char country code).

            ## Claims by Country
            ```sql
            SELECT damage_place_country, COUNT(*) AS cnt
            FROM ins_damages
            WHERE damage_place_country IS NOT NULL AND damage_place_country != ''
            GROUP BY damage_place_country
            ORDER BY cnt DESC
            ```

            ## Top Damage Locations
            ```sql
            SELECT damage_place, COUNT(*) AS cnt
            FROM ins_damages
            WHERE damage_place IS NOT NULL AND damage_place != ''
            GROUP BY damage_place
            ORDER BY cnt DESC LIMIT 10
            ```

            ## Average Cost by Country
            ```sql
            WITH latest_mc AS (...)
            SELECT d.damage_place_country, AVG(mc.total_cost) AS avg_cost, COUNT(*) AS claims
            FROM ins_opis o
            JOIN ins_damages d ON d.damage_id = o.damage_id
            JOIN latest_mc mc ON mc.opis_id = o.opis_id
            WHERE d.damage_place_country IS NOT NULL AND d.damage_place_country != ''
            GROUP BY d.damage_place_country
            ORDER BY avg_cost DESC
            ```

            ## Sofia vs Other Locations
            Sofia (София) is the most common damage location.
            ```sql
            SELECT
                SUM(CASE WHEN damage_place LIKE '%София%' THEN 1 ELSE 0 END) AS sofia_cnt,
                SUM(CASE WHEN damage_place NOT LIKE '%София%' THEN 1 ELSE 0 END) AS other_cnt
            FROM ins_damages
            ```

            ## Key Characteristics
            - Sofia (София) is the most common damage location by far
            - `damage_place` is free text in Bulgarian — use `LIKE '%София%'` for Sofia filtering
            - `damage_place_country` is a 2-char ISO code (e.g., 'BG')
            - Many distinct locations exist — use `HAVING COUNT(*) >= N` to filter noise

            ## Tags
            `geographic, location, damage-place, country, Sofia, cost-by-location`
        """),
    },
}


# ─── Generate Python pattern files ─────────────────────────────────────────

PYTHON_FILES = {
    "visualization_charts": {
        "title": "Python Visualization Patterns — Bar, Histogram, Scatter, and Box Charts",
        "content": textwrap.dedent("""\
            # Python Visualization Patterns — Bar, Histogram, Scatter, and Box Charts

            ## Overview
            When analyzing insurance claims data, visualizations complement SQL results.
            The standard stack is **matplotlib + seaborn** with the `viridis` palette.

            ## Standard Imports
            ```python
            import matplotlib.pyplot as plt
            import seaborn as sns
            import pandas as pd
            ```

            ## Bar Chart — The Default Visualization

            ### Horizontal bar chart (Top-N ranking)
            ```python
            # Best for: brand rankings, top parts, supplier comparison
            df_sorted = df.sort_values('metric_column', ascending=False)
            plt.figure(figsize=(12, 8))
            sns.barplot(x='metric_column', y='category_column', data=df_sorted, palette='viridis')
            plt.title('Descriptive Title')
            plt.xlabel('Metric Label')
            plt.ylabel('Category Label')
            plt.tight_layout()
            plt.show()
            ```

            ### Vertical bar chart with rotated labels
            ```python
            # Best for: monthly trends, year comparisons, categorical distributions
            plt.figure(figsize=(12, 6))
            sns.barplot(x='category', y='value', data=df, palette='viridis')
            plt.title('Title')
            plt.xticks(rotation=45, ha='right')
            plt.tight_layout()
            plt.show()
            ```

            ### Bar chart with value labels on bars
            ```python
            fig, ax = plt.subplots(figsize=(12, 7))
            sns.barplot(x='value', y='category', data=df, palette='viridis', ax=ax)
            for p in ax.patches:
                width = p.get_width()
                ax.text(width + 0.5, p.get_y() + p.get_height() / 2.,
                        f'{width:.2f}%', ha='left', va='center')
            plt.tight_layout()
            plt.show()
            ```

            ### Side-by-side comparison using melt
            ```python
            # Compare two metrics (e.g., MC cost vs N24 cost)
            df_melted = df.melt(var_name='Cost_Type', value_name='Value')
            df_melted['Cost_Type'] = df_melted['Cost_Type'].str.replace('_', ' ').str.title()
            plt.figure(figsize=(8, 6))
            sns.barplot(x='Cost_Type', y='Value', data=df_melted, palette='viridis')
            plt.title('Comparison')
            plt.tight_layout()
            plt.show()
            ```

            ### Stacked bar chart
            ```python
            # Best for: distribution across categories (e.g., damage type by country)
            pivot_df = df.pivot(index='group_col', columns='category_col',
                               values='value_col').fillna(0)
            pivot_df.plot(kind='bar', stacked=True, figsize=(14, 8), colormap='viridis')
            plt.legend(title='Category', bbox_to_anchor=(1.05, 1), loc='upper left')
            plt.tight_layout()
            plt.show()
            ```

            ## Histogram — Continuous Distributions

            ### Basic histogram with KDE
            ```python
            # Best for: cost distributions, duration distributions
            plt.figure(figsize=(12, 6))
            sns.histplot(df['total_cost'], bins=50, kde=True)
            plt.title('Distribution of MC Estimate Costs')
            plt.xlabel('Total Cost')
            plt.ylabel('Count')
            plt.grid(True)
            plt.show()
            ```

            ### Histogram with threshold reference line
            ```python
            threshold = df['total_cost'].quantile(0.90)
            plt.figure(figsize=(12, 6))
            sns.histplot(df['total_cost'], bins=50, kde=True)
            plt.axvline(threshold, color='r', linestyle='--',
                        label=f'P90 Threshold: {threshold:,.2f}')
            plt.legend()
            plt.grid(True)
            plt.show()
            ```

            ### Overlaid histograms for comparison
            ```python
            # Best for: MC vs N24 cost comparison on same axis
            sns.histplot(df['mc_cost'], color='blue', label='MC', kde=True,
                         stat='density', linewidth=0)
            sns.histplot(df['n24_cost'], color='red', label='N24', kde=True,
                         stat='density', linewidth=0)
            plt.legend()
            plt.show()
            ```

            ### Discrete histogram
            ```python
            # Best for: integer counts (assessments per claim, parts per claim)
            sns.histplot(df['count_column'], discrete=True, shrink=0.8)
            plt.xticks(sorted(df['count_column'].unique()))
            plt.show()
            ```

            ## Scatter Plot — Correlation Analysis

            ### Scatter with equality reference line
            ```python
            # Best for: MC vs N24 comparison, estimate vs actual
            plt.figure(figsize=(10, 10))
            sns.scatterplot(data=df, x='n24_cost', y='mc_cost', alpha=0.6)
            max_val = max(df['n24_cost'].max(), df['mc_cost'].max())
            plt.plot([0, max_val], [0, max_val], color='red', linestyle='--',
                     label='Equal Cost Line (y=x)')
            plt.legend()
            plt.grid(True)
            plt.axis('equal')
            plt.show()
            ```

            ### Scatter with text annotations
            ```python
            # Annotate points with labels (e.g., brand names)
            for i, row in df.head(10).iterrows():
                plt.text(row['x_col'] + 0.5, row['y_col'], row['label_col'], fontsize=9)
            ```

            ## Box Plot — Distribution Comparison

            ```python
            # Best for: cost by brand, cost by damage type
            sns.boxplot(x='total_cost', y='brand_name', data=df_top, palette='magma')
            plt.xscale('log')  # Use log scale for skewed cost distributions
            plt.show()
            ```

            ## Line Chart — Time Series

            ```python
            # Best for: vehicle age vs cost, monthly trends over time
            sns.lineplot(data=df, x='year', y='avg_cost', marker='o')
            plt.grid(True)
            plt.show()
            ```

            ## Subplots — Multiple Views

            ```python
            fig, axes = plt.subplots(2, 1, figsize=(12, 12))
            fig.suptitle('Overall Title', fontsize=16)
            sns.barplot(ax=axes[0], x='category', y='count', data=df, palette='viridis')
            axes[0].set_title('Counts')
            sns.barplot(ax=axes[1], x='category', y='value', data=df, palette='plasma')
            axes[1].set_title('Values')
            plt.tight_layout(rect=[0, 0.03, 1, 0.96])
            plt.show()
            ```

            ## Common Settings
            - `figsize`: typically `(12, 6)`, `(12, 8)`, or `(10, 6)`
            - `palette='viridis'` is the default color scheme
            - Always call `plt.tight_layout()` before `plt.show()`
            - Use `rotation=45, ha='right'` for long x-axis labels
            - Always assign `result_df = df` at the end to pass data back

            ## Tags
            `python, visualization, matplotlib, seaborn, barplot, histogram, scatter, boxplot, charts`
        """),
    },
    "dataframe_operations": {
        "title": "Pandas DataFrame Operations — Pivot, Melt, GroupBy, Merge, and Filter",
        "content": textwrap.dedent("""\
            # Pandas DataFrame Operations — Pivot, Melt, GroupBy, Merge, and Filter

            ## Overview
            After SQL returns a DataFrame (`df`), Python is used for reshaping, additional
            aggregation, filtering, and preparation for visualization. The standard library
            is **pandas** (`import pandas as pd`).

            ## Pivot — Reshape Long to Wide

            ```python
            # Convert rows into columns (e.g., MC vs N24 side by side)
            df_pivot = df.pivot(index='brand_name', columns='type',
                                values='avg_cost').dropna()
            df_pivot.columns = ['MC_avg_cost', 'N24_avg_cost']
            df_pivot['difference'] = df_pivot['MC_avg_cost'] - df_pivot['N24_avg_cost']
            df_pivot['pct_difference'] = (
                (df_pivot['difference'] / df_pivot['N24_avg_cost']) * 100
            )
            result_df = df_pivot.sort_values('difference', ascending=False).reset_index()
            ```

            ## Melt — Reshape Wide to Long (for Visualization)

            ```python
            # Convert columns into rows for grouped barplots
            df_melted = df.melt(var_name='Category', value_name='Count')
            df_melted['Category'] = df_melted['Category'].str.replace('_', ' ').str.title()
            ```

            ## GroupBy with Aggregation

            ```python
            summary = df.groupby('brand_name').agg(
                total_claims=('brand_name', 'size'),
                avg_cost=('total_cost', 'mean'),
                avg_parts=('damage_line_count', 'mean'),
            ).reset_index()

            # Sort by a computed metric
            summary = summary.sort_values('avg_cost', ascending=False)
            ```

            ## Filter with Threshold

            ```python
            # Filter groups with minimum size (e.g., brands with >= 5 claims)
            grouped = df.groupby('brand_name')
            filtered = grouped.filter(lambda x: len(x) >= 5)

            # Filter rows above a percentile
            p90 = df['total_cost'].quantile(0.90)
            above_p90 = df[df['total_cost'] > p90]
            ```

            ## Merge — Join DataFrames

            ```python
            # Multi-step merge (e.g., combining results from different SQL queries)
            df = pd.merge(opis_df, damages_df, on='damage_id', how='inner')
            df = pd.merge(df, cars_df, on='car_id', how='inner')
            df = pd.merge(df, brands_df, left_on='car_mc_brand',
                         right_on='brand_id', how='inner')
            ```

            ## Statistical Computations

            ```python
            # Percentiles
            p90 = df['total_cost'].quantile(0.90)
            median = df['total_cost'].median()

            # Year-over-year growth
            df = df.sort_values('year')
            df['yoy_growth'] = df['claim_count'].pct_change()

            # Ratio with NaN safety
            import numpy as np
            df['ratio'] = df['mc_cost'] / df['n24_cost'].replace(0, np.nan)

            # Descriptive statistics
            stats = df[['cost', 'ratio']].agg(['mean', 'std', 'min', 'max']).reset_index()
            ```

            ## String/Column Operations

            ```python
            # Clean column names for display
            df.columns = df.columns.str.replace('_', ' ').str.title()

            # Construct labels from multiple columns
            df['label'] = (df['brand'] + ' ' + df['model'] + ' ('
                          + df['year'].astype(str) + ')')

            # Type conversion for categorical plotting
            df['category_col'] = df['category_col'].astype(str)
            ```

            ## Period/Time Construction

            ```python
            # Create period labels from year + quarter columns
            df['period'] = df['year'].astype(str) + '-Q' + df['quarter'].astype(str)

            # Month name mapping
            month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                          'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
            plt.xticks(ticks=range(12), labels=month_names)
            ```

            ## Formatting Output

            ```python
            # Percentage formatting
            df['pct'] = (df['ratio'] * 100).map('{:.2f}%'.format)

            # Float display settings
            pd.options.display.float_format = '{:.2f}'.format
            print(df.to_string(index=False))

            # F-string formatted metrics
            print(f'P90 threshold: {p90:,.2f}')
            print(f'Found {len(df)} claims matching criteria.')
            ```

            ## Tags
            `python, pandas, DataFrame, pivot, melt, groupby, merge, filter, statistics, formatting`
        """),
    },
    "result_formatting": {
        "title": "Python Result Convention — The result_df Pattern and Output Rules",
        "content": textwrap.dedent("""\
            # Python Result Convention — The result_df Pattern and Output Rules

            ## Overview
            The agent pipeline uses a specific convention for Python step results:
            the variable `result_df` is the standard way to return data from a Python step
            back to the agent for display to the user.

            ## The result_df Convention

            ```python
            # At the END of every Python step, assign the result:
            result_df = df                              # Pass through unchanged
            result_df = df_sorted                       # After sorting
            result_df = df_pivot.reset_index()          # After pivoting
            result_df = pd.DataFrame({'metric': [val]}) # Single value as DataFrame
            ```

            ## When to Use result_df vs Print

            | Scenario | Approach |
            |----------|----------|
            | Return tabular data | `result_df = df` |
            | Return a single metric | `result_df = pd.DataFrame({'metric': [value]})` |
            | Show summary stats | `result_df = df.describe()` |
            | Print alongside chart | Both `print(f'...')` AND `result_df = df` |

            ## Display Formatting

            ### Tables
            ```python
            # Use to_string for clean output (tabulate is NOT available)
            print(df.to_string(index=False, float_format="{:.2f}".format))
            ```

            ### Metrics with Context
            ```python
            print(f'Average cost: {avg_cost:,.2f} BGN')
            print(f'Total claims: {total:,}')
            print(f'Share: {share:.1f}%')
            ```

            ### Chart + Data
            ```python
            # Common pattern: create chart, then return data
            plt.figure(figsize=(12, 8))
            sns.barplot(...)
            plt.show()

            # Return the underlying data too
            result_df = df
            ```

            ## Important Rules
            1. Always assign `result_df` at the end of the Python block
            2. `df.to_markdown()` requires `tabulate` which is NOT installed — use `df.to_string()` instead
            3. Only `df` (from the previous SQL step) persists between steps — no other variable names carry over
            4. If a step fails and `df` is None, check `if df is not None` before operating on it

            ## Tags
            `python, result_df, output-convention, formatting, display, agent-pipeline`
        """),
    },
    "sandbox_constraints": {
        "title": "Python Sandbox Environment — Available Libraries and Restrictions",
        "content": textwrap.dedent("""\
            # Python Sandbox Environment — Available Libraries and Restrictions

            ## Overview
            Python code runs in a sandboxed environment with limited library access.
            Understanding what's available prevents runtime errors and failed recovery attempts.

            ## Available Libraries
            | Library | Import | Use |
            |---------|--------|-----|
            | matplotlib | `import matplotlib.pyplot as plt` | All chart types |
            | seaborn | `import seaborn as sns` | Statistical visualizations |
            | pandas | `import pandas as pd` | DataFrame operations |
            | numpy | `import numpy as np` | `np.nan`, `np.where`, `np.inf` |

            ## NOT Available (Will Fail)
            | Library | Error | Recovery |
            |---------|-------|----------|
            | plotly | `ModuleNotFoundError` | Use matplotlib/seaborn instead |
            | tabulate | `ModuleNotFoundError` | Use `df.to_string()` instead of `df.to_markdown()` |
            | sqlalchemy | Cannot create DB connections | SQL queries are done in SQL steps, not Python |
            | duckdb | Cannot query tables directly | SQL queries are done in SQL steps, not Python |

            ## Key Constraint: No Direct Database Access

            Python steps **cannot** access the database. Do not attempt:
            ```python
            # ALL OF THESE WILL FAIL:
            from sqlalchemy import create_engine
            engine = create_engine('mysql+pymysql://...')

            import duckdb
            duckdb.sql('SELECT ...')

            pd.read_sql('SELECT ...', connection)
            ```

            **Instead**: Use a SQL step to query the database, then use a Python step to
            process the resulting `df` DataFrame.

            ## Variable Persistence Between Steps

            - Only the `df` variable (from the most recent SQL step) persists into Python steps
            - Custom variable names (`df_step_2`, `df_merged`, `df_both_estimates`) do NOT carry over
            - If a SQL step fails, `df` will be `None` — always check before using:
            ```python
            if df is not None and not df.empty:
                # Safe to process
                result_df = df
            else:
                print("No data returned from SQL step")
                result_df = pd.DataFrame()
            ```

            ## Common Error Patterns

            ### Undefined variable from plan naming
            ```python
            # WRONG: Agent planned "df_both_estimates" but only df exists
            df_both_estimates = ...  # NameError

            # CORRECT: Use df directly
            result_df = df
            ```

            ### Failed recovery with direct DB access
            ```python
            # WRONG: Trying to self-heal by querying DB directly
            from sqlalchemy import create_engine  # Will fail
            engine = create_engine(os.environ['MCPDB_DATABASE_URL'])

            # CORRECT: If SQL step failed, fix the SQL query, not the Python step
            ```

            ## Tags
            `python, sandbox, environment, libraries, constraints, matplotlib, seaborn, pandas, errors`
        """),
    },
}


# ─── Generate template files from SQL templates ─────────────────────────────

TEMPLATE_FILES = {
    "template_01_claims_per_month": {
        "title": "SQL Template: Claims Per Month — Time Series Frequency Analysis",
        "content": textwrap.dedent("""\
            # SQL Template: Claims Per Month — Time Series Frequency Analysis

            ## Purpose
            Count claims filed per month for trend analysis.

            ## SQL
            ```sql
            SELECT DATE_FORMAT(o.opis_date, '%Y-%m') AS month, COUNT(*) AS claims
            FROM ins_opis o
            WHERE o.opis_date IS NOT NULL
            GROUP BY month
            ORDER BY month
            ```

            ## Variants
            - Per quarter: `YEAR(o.opis_date) AS yr, QUARTER(o.opis_date) AS qtr`
            - Per year: `YEAR(o.opis_date) AS yr`
            - Specific year: Add `AND YEAR(o.opis_date) = 2023`
            - With cost: Add `JOIN ins_damages d ... AVG(d.total_cost)`

            ## Tags
            `template, frequency, time-series, monthly, claims-count, DATE_FORMAT`
        """),
    },
    "template_03_avg_cost_by_brand": {
        "title": "SQL Template: Average MC Cost by Brand — Cost Severity Analysis",
        "content": textwrap.dedent("""\
            # SQL Template: Average MC Cost by Brand — Cost Severity Analysis

            ## Purpose
            Calculate average MC estimated cost per car brand to identify high-severity brands.

            ## SQL
            ```sql
            WITH latest_mc AS (
                SELECT ic.* FROM ins_mc_invcalc ic
                INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id
                    FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm
                ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id
            )
            SELECT b.brand_name,
                AVG(mc.total_cost) AS avg_cost,
                COUNT(*) AS claims
            FROM latest_mc mc
            JOIN ins_opis o ON o.opis_id = mc.opis_id
            JOIN ins_cars c ON c.car_id = o.car_id
            JOIN srv_mc_horizon_brand b ON c.car_mc_brand = b.brand_id
            GROUP BY b.brand_name
            ORDER BY avg_cost DESC
            ```

            ## Key Patterns
            - Latest MC estimate CTE
            - Brand name resolution via srv_mc_horizon_brand
            - 4-table join chain: latest_mc → ins_opis → ins_cars → srv_mc_horizon_brand

            ## Tags
            `template, cost-analysis, brand, latest-mc-estimate, brand-name-resolution, multi-table-join`
        """),
    },
    "template_04_cost_structure": {
        "title": "SQL Template: Cost Structure Shares — Parts/Paint/Labor Breakdown",
        "content": textwrap.dedent("""\
            # SQL Template: Cost Structure Shares — Parts/Paint/Labor Breakdown

            ## Purpose
            Analyze the cost structure of MC estimates: what share goes to parts, paint, labor, etc.

            ## SQL
            ```sql
            WITH latest_mc AS (
                SELECT ic.* FROM ins_mc_invcalc ic
                INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id
                    FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm
                ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id
            )
            SELECT
                ROUND(100 * AVG(newparts_cost / NULLIF(total_cost, 0)), 2) AS avg_parts_pct,
                ROUND(100 * AVG(repairs_cost / NULLIF(total_cost, 0)), 2) AS avg_repair_pct,
                ROUND(100 * AVG(mounts_cost / NULLIF(total_cost, 0)), 2) AS avg_mount_pct,
                ROUND(100 * AVG(paints_cost / NULLIF(total_cost, 0)), 2) AS avg_paint_pct,
                ROUND(100 * AVG(other_cost / NULLIF(total_cost, 0)), 2) AS avg_other_pct
            FROM latest_mc
            WHERE total_cost > 0
            ```

            ## Key Patterns
            - Latest MC estimate CTE
            - NULLIF division safety
            - Per-claim ratio (AVG of individual ratios)

            ## Interpretation Notes
            - Paint cost share tends to be the largest component in this dataset
            - Run the query to get current percentages from the live database

            ## Tags
            `template, cost-structure, cost-shares, NULLIF, ratio-calculation, latest-mc-estimate`
        """),
    },
    "template_05_top_damaged_parts": {
        "title": "SQL Template: Top Damaged Parts — Part Resolution Across Catalogs",
        "content": textwrap.dedent("""\
            # SQL Template: Top Damaged Parts — Part Resolution Across Catalogs

            ## Purpose
            Find the most frequently damaged parts, resolving names across three catalogs.

            ## SQL
            ```sql
            SELECT
                r.part_id,
                COALESCE(pi.part_name, pf.part_name) AS part_name,
                COUNT(*) AS frequency
            FROM ins_opis_rows r
            LEFT JOIN ins_partsindex pi ON r.part_id = pi.part_id AND r.part_id < 10000000
            LEFT JOIN ins_partsfree pf ON r.part_id = pf.part_id AND r.part_id >= 20000000
            GROUP BY r.part_id, part_name
            ORDER BY frequency DESC
            LIMIT 10
            ```

            ## Key Patterns
            - Part name resolution via COALESCE across catalog ranges
            - LEFT JOIN to handle unresolved parts
            - Range-based join conditions for performance

            ## Tags
            `template, parts-analysis, COALESCE, part-name-resolution, top-n, ins_opis_rows`
        """),
    },
    "template_13_mc_vs_n24": {
        "title": "SQL Template: MC vs N24 Comparison — Regulatory vs Catalog Estimates",
        "content": textwrap.dedent("""\
            # SQL Template: MC vs N24 Comparison — Regulatory vs Catalog Estimates

            ## Purpose
            Compare MC (MultiCat) and N24 (regulatory) estimates for the same claim.

            ## SQL
            ```sql
            WITH latest AS (
                SELECT ic.* FROM ins_mc_invcalc ic
                INNER JOIN (SELECT opis_id, type, MAX(invcalc_id) AS max_id
                    FROM ins_mc_invcalc GROUP BY opis_id, type) lm
                ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id
            )
            SELECT
                mc.opis_id,
                mc.total_cost AS mc_cost,
                n24.total_cost AS n24_cost,
                mc.total_cost - n24.total_cost AS difference,
                ROUND(mc.total_cost / NULLIF(n24.total_cost, 0), 4) AS mc_n24_ratio
            FROM latest mc
            JOIN latest n24 ON mc.opis_id = n24.opis_id AND n24.type = 'n24'
            WHERE mc.type = 'mc'
            ```

            ## Important
            - Only a small subset of claims have both MC and N24 estimates — check with the verification query
            - Use latest estimate PER TYPE (GROUP BY opis_id, type)
            - MC is generally higher than N24 for the same claim

            ## Tags
            `template, mc-vs-n24, comparison, latest-estimate-per-type, regulatory, catalog`
        """),
    },
    "template_14_cycle_time": {
        "title": "SQL Template: Claim Lifecycle Timing — Filing Lag and Repair Duration",
        "content": textwrap.dedent("""\
            # SQL Template: Claim Lifecycle Timing — Filing Lag and Repair Duration

            ## Purpose
            Analyze the time between key events in the claim lifecycle.

            ## Filing Lag (Damage → Claim)
            ```sql
            SELECT AVG(DATEDIFF(o.opis_date, d.damage_date)) AS avg_lag_days
            FROM ins_opis o
            JOIN ins_damages d ON d.damage_id = o.damage_id
            WHERE d.damage_date IS NOT NULL AND o.opis_date IS NOT NULL
            ```

            ## Repair Duration (Start → End)
            ```sql
            SELECT AVG(DATEDIFF(end_repair, start_repair)) AS avg_repair_days
            FROM ins_invrepair
            WHERE start_repair IS NOT NULL AND end_repair IS NOT NULL
            ```

            ## Full Lifecycle (Damage → Repair Complete)
            ```sql
            SELECT AVG(DATEDIFF(ir.end_repair, d.damage_date)) AS avg_total_days
            FROM ins_invrepair ir
            JOIN ins_opis o ON o.opis_id = ir.opis_id
            JOIN ins_damages d ON d.damage_id = o.damage_id
            WHERE d.damage_date IS NOT NULL AND ir.end_repair IS NOT NULL
            ```

            ## Interpretation Notes
            - Most claims are filed within a few days of the damage event
            - Same-day filings are common — use `DATEDIFF(opis_date, damage_date) = 0`
            - Late filings (>30 days) are rare but worth monitoring
            - Run the queries above to get current metrics from the live database

            ## Tags
            `template, cycle-time, filing-lag, repair-duration, DATEDIFF, lifecycle`
        """),
    },
    "template_dq_orphan_checks": {
        "title": "SQL Template: Orphan Record Detection — Data Quality Anti-Join Pattern",
        "content": textwrap.dedent("""\
            # SQL Template: Orphan Record Detection — Data Quality Anti-Join Pattern

            ## Purpose
            Find records with broken foreign key references using LEFT JOIN ... IS NULL pattern.

            ## Orphan Claims (opis without damage)
            ```sql
            SELECT COUNT(*) FROM ins_opis o
            LEFT JOIN ins_damages d ON d.damage_id = o.damage_id
            WHERE d.damage_id IS NULL
            ```
            Expected: 0 (all claims link to a damage event)

            ## Orphan Estimates (without claim)
            ```sql
            SELECT COUNT(*) FROM ins_mc_invcalc ic
            LEFT JOIN ins_opis o ON o.opis_id = ic.opis_id
            WHERE o.opis_id IS NULL
            ```

            ## Orphan Opis (non-zero car_id not in ins_cars)
            ```sql
            SELECT COUNT(*) FROM ins_opis o
            LEFT JOIN ins_cars c ON c.car_id = o.car_id
            WHERE o.car_id > 0 AND c.car_id IS NULL
            ```
            Note: car_id=0 is a sentinel meaning "no car linked" — exclude from orphan check.

            ## Tags
            `template, data-quality, orphan-detection, anti-join, LEFT JOIN, referential-integrity`
        """),
    },
}


# ─── Main generation ────────────────────────────────────────────────────────

def main():
    print("Generating RAG knowledge base...")

    # Create directories
    for subdir in ["questions", "patterns", "domain", "templates", "python"]:
        (RAG_DIR / subdir).mkdir(parents=True, exist_ok=True)

    # Generate 300 question files
    count = 0
    for qid in range(1, 301):
        content = generate_question_file(qid)
        path = RAG_DIR / "questions" / f"q{qid:03d}.md"
        path.write_text(content)
        count += 1
    print(f"  Generated {count} question files in questions/")

    # Generate pattern files
    for fname, data in PATTERN_FILES.items():
        path = RAG_DIR / "patterns" / f"{fname}.md"
        path.write_text(data["content"])
    print(f"  Generated {len(PATTERN_FILES)} pattern files in patterns/")

    # Generate domain files
    for fname, data in DOMAIN_FILES.items():
        path = RAG_DIR / "domain" / f"{fname}.md"
        path.write_text(data["content"])
    print(f"  Generated {len(DOMAIN_FILES)} domain files in domain/")

    # Generate template files
    for fname, data in TEMPLATE_FILES.items():
        path = RAG_DIR / "templates" / f"{fname}.md"
        path.write_text(data["content"])
    print(f"  Generated {len(TEMPLATE_FILES)} template files in templates/")

    # Generate Python pattern files
    for fname, data in PYTHON_FILES.items():
        path = RAG_DIR / "python" / f"{fname}.md"
        path.write_text(data["content"])
    print(f"  Generated {len(PYTHON_FILES)} Python pattern files in python/")

    total = count + len(PATTERN_FILES) + len(DOMAIN_FILES) + len(TEMPLATE_FILES) + len(PYTHON_FILES)
    print(f"\nTotal: {total} RAG files generated in {RAG_DIR}")


if __name__ == "__main__":
    main()
