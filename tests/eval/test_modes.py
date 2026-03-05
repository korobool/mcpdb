#!/usr/bin/env python3
"""End-to-end mode tests — runs mcpdb query for each mode and verifies answers.

Ground truth is derived from direct SQL queries against the bgins database.
Each question targets a specific agent mode and checks for key facts in the response.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import time

DB_URL = "mysql+pymysql://dbtalk:dbtalk@localhost:3306/bgins"

_skip_interrupt = False

# Per-mode timeouts (seconds) — None means no timeout (run until done)
MODE_TIMEOUTS: dict[str, int | None] = {
    "quick": 120,
    "simple": 120,
    "optimization": 300,
    "extended": 600,
    "deep": None,  # Deep mode can run for a long time
}

# ── Ground Truth (verified via direct SQL) ──────────────────────────
# Total tables: 21
# Total cars: 1105
# Total damages: 2141
# Date range: 2021-02-17 to 2026-02-23
# Top make by car count: Mercedes (make_id=8, 133 cars)
# Top make by damage count: Mercedes (274), BMW (257), Audi (234), VW (220)
# damage_typeid=0: 2037 (95.1%)
# Total opis: 2141
# Average total_cost ≈ 597.8
# Max total_cost ≈ 32013.29

QUESTIONS: list[dict] = [
    # ── QUICK MODE (schema/metadata, no SQL needed) ──
    {
        "id": "Q1",
        "mode": "quick",
        "question": "How many tables are in the database?",
        "checks": [r"21"],
        "description": "Should answer from schema context",
    },
    {
        "id": "Q2",
        "mode": "quick",
        "question": "List the primary key column of the ins_cars table",
        "checks": [r"car_id"],
        "description": "Schema lookup",
    },

    # ── SIMPLE MODE (1-5 steps, focused queries) ──
    {
        "id": "Q3",
        "mode": "simple",
        "question": "How many cars are registered in the database?",
        "checks": [r"1[,.]?105"],
        "description": "Simple COUNT(*) from ins_cars",
    },
    {
        "id": "Q4",
        "mode": "simple",
        "question": "What is the maximum total damage cost in the database?",
        "checks": [r"32[,.]?013"],
        "description": "MAX(total_cost) from ins_damages",
    },
    {
        "id": "Q5",
        "mode": "simple",
        "question": "How many damage claims have damage_typeid = 0?",
        "checks": [r"2[,.]?037"],
        "description": "COUNT with WHERE filter",
    },
    {
        "id": "Q6",
        "mode": "simple",
        "question": "What is the earliest damage date in the database?",
        "checks": [r"2021.02.17|2021-02-17|February.*2021|17.*Feb.*2021"],
        "description": "MIN(damage_date)",
    },

    # ── EXTENDED MODE (5+ steps, comprehensive analysis) ──
    {
        "id": "Q7",
        "mode": "extended",
        "question": "Perform a 5 step analysis of damage costs by car make. Include totals, averages, and counts.",
        "checks": [r"[Mm]ercedes|BMW|[Aa]udi|[Vv]olkswagen|[Tt]oyota"],
        "description": "Multi-step aggregation with JOINs",
    },
    {
        "id": "Q8",
        "mode": "extended",
        "question": "Do a 5 step exploratory analysis of the ins_damages table. Show distributions, outliers, and trends over time.",
        "checks": [r"(?i)(distribution|trend|outlier|cost|damage)"],
        "description": "EDA with multiple analytical steps",
    },

    # ── OPTIMIZATION MODE (cost-aware for large tables) ──
    {
        "id": "Q9",
        "mode": "optimization",
        "question": "What are the top 10 most expensive individual expense items across all 39000+ invoice expense records?",
        "checks": [r"\d+"],
        "description": "Targets ins_mc_invexpenses (39K rows), should optimize",
    },

    # ── DEEP MODE (multi-investigation research) ──
    {
        "id": "Q10",
        "mode": "deep",
        "question": "Deep investigation: How does car make affect damage costs? Compare average costs and claim frequency across makes.",
        "checks": [r"(?i)(make|cost|mercedes|bmw|audi|average|frequency)"],
        "description": "Focused deep analysis (2-3 investigations)",
    },
]


def _load_env() -> dict[str, str]:
    """Load environment variables, including from .run.sh if needed."""
    env = os.environ.copy()
    if "GEMINI_API_KEY" not in env:
        run_sh = os.path.join(os.path.dirname(__file__), "..", "..", ".run.sh")
        if os.path.exists(run_sh):
            with open(run_sh) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("export ") and "=" in line:
                        key, val = line[7:].split("=", 1)
                        env[key.strip()] = val.strip().strip('"')
    return env


def run_query(question: str, timeout: int | None = 300) -> tuple[str, float, int]:
    """Run mcpdb query and return (output, elapsed_seconds, return_code)."""
    env = _load_env()
    cmd = ["mcpdb", "query", DB_URL, question]
    t0 = time.time()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, env=env,
        )
        elapsed = time.time() - t0
        output = result.stdout + result.stderr
        return output, elapsed, result.returncode
    except subprocess.TimeoutExpired:
        elapsed = time.time() - t0
        return f"TIMEOUT after {timeout}s", elapsed, -1


def run_query_interruptible(question: str, interrupt_after: float = 30.0) -> tuple[str, float, int, bool]:
    """Start mcpdb query, send SIGINT after interrupt_after seconds, check graceful exit.

    Returns (output, elapsed_seconds, return_code, clean_exit).
    clean_exit is True if the process exited within 10s after SIGINT.
    """
    env = _load_env()
    cmd = ["mcpdb", "query", DB_URL, question]
    t0 = time.time()

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
    )

    # Wait for the process to start working
    time.sleep(interrupt_after)

    # Send SIGINT (Ctrl+C)
    proc.send_signal(signal.SIGINT)

    # Wait up to 10s for clean exit
    try:
        stdout, stderr = proc.communicate(timeout=10)
        elapsed = time.time() - t0
        clean_exit = True
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        elapsed = time.time() - t0
        clean_exit = False

    output = (stdout or "") + (stderr or "")
    return output, elapsed, proc.returncode, clean_exit


def check_response(output: str, checks: list[str]) -> tuple[bool, list[str]]:
    """Check if output matches all expected patterns. Returns (pass, failures)."""
    failures = []
    for pattern in checks:
        if not re.search(pattern, output):
            failures.append(f"Missing: /{pattern}/")
    return len(failures) == 0, failures


def print_preview(output: str) -> None:
    """Print a preview of the response output."""
    response_lines = output.strip().split("\n")
    # Skip spinner lines (start with \r or contain spinner chars)
    clean_lines = [l for l in response_lines if not l.startswith("\r") and "\u2807\u2819\u2839" not in l]
    preview = "\n".join(clean_lines[:8])
    if len(clean_lines) > 8:
        preview += f"\n  ... ({len(clean_lines)} lines total)"
    print(f"\n  Response preview:")
    for line in preview.split("\n")[:8]:
        print(f"    {line[:100]}")


def run_interrupt_test() -> dict:
    """Test that deep mode can be interrupted with SIGINT."""
    print(f"\n{'─' * 70}")
    print(f"  Q11 [DEEP/INTERRUPT] Testing graceful SIGINT handling...")
    print(f"  Send SIGINT after 30s, verify clean exit within 10s")
    print(f"{'─' * 70}")

    question = "Deep investigation: Analyze all damage patterns across the entire database comprehensively."
    output, elapsed, rc, clean_exit = run_query_interruptible(question, interrupt_after=30.0)

    if clean_exit:
        status = "PASS"
        passed = True
        failures = []
    else:
        status = "FAIL"
        passed = False
        failures = ["Process did not exit cleanly within 10s after SIGINT"]

    symbol = "\u2713" if passed else "\u2717"
    print(f"\n  {symbol} {status} ({elapsed:.0f}s)")
    if failures:
        for f in failures:
            print(f"    {f}")
    print(f"  Clean exit after SIGINT: {clean_exit}")

    return {
        "id": "Q11",
        "mode": "deep/interrupt",
        "status": status,
        "elapsed": elapsed,
        "passed": passed,
    }


def main():
    print("=" * 70)
    print("MCPDB Mode Tests \u2014 End-to-End Verification")
    print("=" * 70)

    # Check API key
    env_key = os.environ.get("GEMINI_API_KEY", "")
    if not env_key:
        run_sh = os.path.join(os.path.dirname(__file__), "..", "..", ".run.sh")
        if os.path.exists(run_sh):
            with open(run_sh) as f:
                for line in f:
                    if "GEMINI_API_KEY" in line:
                        env_key = "found in .run.sh"
    if not env_key:
        print("ERROR: GEMINI_API_KEY not set. Source .run.sh first.")
        sys.exit(1)

    results = []
    total_time = 0

    for q in QUESTIONS:
        qid = q["id"]
        mode = q["mode"]
        question = q["question"]
        checks = q["checks"]
        desc = q["description"]

        print(f"\n{'─' * 70}")
        print(f"  {qid} [{mode.upper()}] {question[:60]}...")
        print(f"  {desc}")
        print(f"{'─' * 70}")

        timeout = MODE_TIMEOUTS.get(mode, 300)
        timeout_str = f"{timeout}s" if timeout else "no limit"
        print(f"  Timeout: {timeout_str}")

        output, elapsed, rc = run_query(question, timeout=timeout)
        total_time += elapsed

        if rc == -1:
            status = "TIMEOUT"
            passed = False
            failures = ["Timed out"]
        elif rc != 0:
            status = "ERROR"
            passed = False
            failures = [f"Exit code {rc}"]
        else:
            passed, failures = check_response(output, checks)
            status = "PASS" if passed else "FAIL"

        symbol = "\u2713" if passed else "\u2717"
        print(f"\n  {symbol} {status} ({elapsed:.0f}s)")
        if failures:
            for f in failures:
                print(f"    {f}")
        print_preview(output)

        results.append({
            "id": qid,
            "mode": mode,
            "status": status,
            "elapsed": elapsed,
            "passed": passed,
        })

    # Interrupt test (only if deep mode is included and not skipped)
    if any(q["mode"] == "deep" for q in QUESTIONS) and not _skip_interrupt:
        r = run_interrupt_test()
        total_time += r["elapsed"]
        results.append(r)

    # Summary
    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print(f"{'=' * 70}")

    passed_count = sum(1 for r in results if r["passed"])
    total_count = len(results)

    for r in results:
        symbol = "\u2713" if r["passed"] else "\u2717"
        print(f"  {symbol} {r['id']:4s} [{r['mode']:15s}] {r['status']:7s} ({r['elapsed']:.0f}s)")

    print(f"\n  {passed_count}/{total_count} passed in {total_time:.0f}s total")

    if passed_count < total_count:
        sys.exit(1)


if __name__ == "__main__":
    # Support --only Q7,Q10 or --mode extended,deep filters
    import argparse
    parser = argparse.ArgumentParser(description="MCPDB mode tests")
    parser.add_argument("--only", help="Comma-separated question IDs (e.g. Q7,Q10)")
    parser.add_argument("--mode", help="Comma-separated modes (e.g. extended,deep)")
    parser.add_argument("--no-interrupt", action="store_true", help="Skip interrupt test")
    cli_args = parser.parse_args()

    if cli_args.only:
        ids = {x.strip().upper() for x in cli_args.only.split(",")}
        QUESTIONS = [q for q in QUESTIONS if q["id"] in ids]
    if cli_args.mode:
        modes = {x.strip().lower() for x in cli_args.mode.split(",")}
        QUESTIONS = [q for q in QUESTIONS if q["mode"] in modes]

    _skip_interrupt = cli_args.no_interrupt
    main()
