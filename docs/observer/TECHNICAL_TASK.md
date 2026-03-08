# Async Reasoning Observer — Technical Task

## 1. Problem Statement

MCPDB's agent pipeline (quick → simple → optimization → extended → deep) executes
LLM-driven plans that can:

- **Hang or loop**: plan/execute/debug cycles that never converge.
- **Over-think**: spending 60s of LLM reasoning on a question answerable in 5s.
- **Under-think**: quick mode produces empty results, escalation is slow.
- **Fail silently**: errors swallowed, wrong answers returned without detection.
- **Waste tokens**: redundant re-planning, verbose prompts for simple queries.

## 2. Solution: Async Reasoning Observer

A **parallel, non-blocking observer** that monitors agent execution in real-time,
detects anomalies, and can intervene — without ever slowing the main pipeline.

### 2.1 Architecture

```
┌─────────────────────────────────────────────┐
│              Agent Pipeline                  │
│  plan → execute → debug → revise → synth    │
│         │    │       │       │               │
│         ▼    ▼       ▼       ▼               │
│     ┌──────────────────────────┐             │
│     │   CallbackManager events │             │
│     └──────────┬───────────────┘             │
│                │ (async queue, zero-copy)     │
└────────────────┼────────────────────────────┘
                 ▼
┌─────────────────────────────────────────────┐
│         Async Reasoning Observer             │
│                                              │
│  ┌──────────┐  ┌───────────┐  ┌──────────┐  │
│  │ Timing   │  │ Pattern   │  │ Decision │  │
│  │ Monitor  │  │ Detector  │  │ Engine   │  │
│  └──────────┘  └───────────┘  └──────────┘  │
│       │              │             │         │
│       ▼              ▼             ▼         │
│  ┌─────────────────────────────────────┐     │
│  │         Observer Actions            │     │
│  │  - Log warning                      │     │
│  │  - Set cancellation flag            │     │
│  │  - Emit user notification           │     │
│  │  - Record anomaly for post-mortem   │     │
│  └─────────────────────────────────────┘     │
└─────────────────────────────────────────────┘
```

### 2.2 Core Principles

1. **Never block**: observer runs in a separate asyncio task, consumes events
   from a queue. Main pipeline posts events and continues immediately.
2. **Never add latency**: event posting is `put_nowait` — if queue is full,
   event is dropped (observer falls behind gracefully).
3. **Cheap by default**: observer does local heuristic checks (timing, pattern
   matching). Only escalates to LLM assessment when anomaly is detected.
4. **Cooperative cancellation**: observer sets a `CancellationToken` flag;
   pipeline checks it at natural boundaries (between steps, before LLM calls).

### 2.3 Components

#### TimingMonitor

Tracks wall-clock time per phase and step:

| Phase        | Expected (quick) | Expected (simple) | Expected (deep) | Alert threshold |
|-------------|------------------|--------------------|-----------------|-----------------|
| plan        | 2-5s             | 5-15s              | 15-30s          | 3× expected     |
| execute     | 1-3s             | 3-10s              | 5-20s           | 3× expected     |
| debug       | 2-5s             | 5-15s              | 10-30s          | 3× expected     |
| synthesize  | 2-5s             | 3-10s              | 5-15s           | 3× expected     |
| total       | 5-15s            | 15-60s             | 60-300s         | 2× expected     |

When alert threshold is exceeded → emit warning, optionally trigger LLM assessment.

#### PatternDetector

Detects known failure patterns:

- **Debug loop**: same error appearing 2+ times in debug cycle.
- **Empty result loop**: execute returns empty DataFrame, plan revises, still empty.
- **Token explosion**: single prompt exceeding 8K tokens for a simple question.
- **Plan oscillation**: plan alternates between two approaches.
- **Stuck phase**: no progress events for >30s.

#### DecisionEngine

When anomaly detected, decides action:

1. **Log & continue** — minor anomaly, record for post-mortem.
2. **Warn user** — emit callback event so UI shows "Taking longer than expected..."
3. **Request simplification** — inject hint into next plan iteration.
4. **Cancel & restart** — set cancellation, trigger restart in simpler mode.
5. **Cancel & report** — give up, report what was found.

## 3. Implementation Plan

### Phase 1: Observer Core (this session)

| Step | File | Description |
|------|------|-------------|
| 1 | `mcpdb/agent/observer.py` | Observer class with TimingMonitor, PatternDetector |
| 2 | `mcpdb/agent/callbacks.py` | Add observer hook to CallbackManager |
| 3 | `mcpdb/agent/graph.py` | Wire observer start/stop around pipeline execution |
| 4 | `tests/test_observer.py` | Unit tests for timing + pattern detection |

### Phase 2: Autonomous Test Harness

| Step | File | Description |
|------|------|-------------|
| 5 | `tests/eval/questions_auto.py` | 40+ questions for DB + CSV (varying complexity) |
| 6 | `tests/eval/run_auto_eval.py` | Autonomous eval runner with observer metrics |
| 7 | Results analysis | Fix discovered issues |

### Phase 3: Optimization

| Step | Description |
|------|-------------|
| 8 | Tune timing thresholds from real data |
| 9 | Add LLM-based assessment for complex anomalies |
| 10 | Token budget optimization |

## 4. Test Questions

### 4.1 Database (bgins — MySQL, 21 tables)

**Quick-tier** (should complete in quick/simple mode, <15s):
1. How many tables are in the database?
2. How many records in ins_cars?
3. What are the column names in ins_damages?
4. Show 5 sample rows from ins_opis
5. What is the average value in ins_damages?

**Simple-tier** (simple/optimization mode, <30s):
6. What car brands appear most frequently in ins_cars?
7. How many claims per year?
8. What is the distribution of damage types?
9. Top 10 most expensive repairs
10. Average repair cost by car brand

**Complex-tier** (optimization/extended, <120s):
11. Correlation between car age and claim frequency
12. Which repair shops have the highest average cost?
13. Monthly trend of claims over all available years
14. Compare repair costs across vehicle categories
15. What percentage of cars have multiple claims?

**Deep-tier** (extended/deep, <300s):
16. Full statistical profile of the claims pipeline
17. Identify potential fraud patterns in repair costs
18. Build a risk scoring model description from the data
19. Compare all repair shops on cost, frequency, and vehicle mix
20. Analyze seasonal patterns across all damage types and regions

### 4.2 CSV (Qala-MTPL-V4.csv — 464K rows, insurance policies)

**Quick-tier:**
21. How many rows and columns?
22. What are the column names?
23. Show 5 sample rows
24. What is the average UnderwritingPremium?
25. How many unique PolicyInsuranceType values?

**Simple-tier:**
26. Distribution of VehicleType
27. Top 10 car brands by policy count
28. Average claim amount by vehicle age
29. What percentage of policies have claims?
30. Premium distribution statistics

**Complex-tier:**
31. Correlation between vehicle age and claim frequency
32. Compare earned premium vs claim amount by insurance class
33. Monthly policy issuance trend
34. Risk profile: claim frequency and severity by vehicle category
35. Top 20 vehicle models by loss ratio

**Deep-tier:**
36. Complete actuarial summary: exposure, frequency, severity, loss ratio by segments
37. Identify high-risk segments combining vehicle, region, and policy features
38. Build a pricing adequacy analysis across all dimensions
39. Compare vehicle depreciation patterns (age vs insured sum)
40. Outlier detection in premium vs claim relationships

### 4.3 CSV (Lithuania-MTPL — 312K rows, Lithuanian insurance)

**Quick-tier:**
41. How many rows?
42. List all columns
43. Average GWP3 value
44. How many unique vehicle types?
45. Show sample data

**Simple-tier:**
46. Distribution of SalesChannel
47. Policy count by region (Holder_address_region)
48. Average premium by BonusMalus class
49. Renewal rate (percentage of Renewal=Y)
50. Top vehicle brands

## 5. Success Criteria

1. Observer detects hangs within 2× expected time (no false positives on legitimate complex queries).
2. Observer detects debug loops within 2 iterations.
3. Zero impact on pipeline latency (< 1ms overhead per event).
4. User-visible warnings appear within 5s of anomaly detection.
5. Post-mortem data captures: question, mode, timing per phase, anomaly type, action taken.
6. All 50 test questions produce correct results without hanging.

## 6. Token/Cost Optimization Strategy

| Optimization | Savings | Implementation |
|-------------|---------|----------------|
| Skip observer LLM calls for < 30s queries | ~80% of observer tokens | Timing gate |
| Compress context for simple queries | ~40% per query | Heuristic context pruning |
| Cache similar question patterns | ~30% for repeated patterns | Experience cache (existing) |
| Early termination on debug loops | ~50% of wasted tokens | Pattern detector |
| Mode-appropriate prompt sizing | ~20% overall | Mode-aware prompt templates |

## 7. Risk Mitigation

- **False positive cancellation**: Observer should only cancel after 2+ anomaly signals.
  Single timeout is a warning, not cancellation.
- **Observer overhead**: Keep event queue bounded (1000 items). Drop events rather
  than blocking.
- **LLM assessment cost**: Gate behind timing threshold. Only assess if query has
  been running > 2× expected time AND a pattern anomaly is detected.
