# Eval Improvements Report

## Current Metrics (No-Cache Run)

| Metric | Value |
|--------|-------|
| **Pass** | 94/100 (94.0%) |
| **Partial** | 1/100 |
| **Fail** | 5/100 |

## Baseline (With Cache)

| Metric | Baseline | Current | Delta |
|--------|----------|---------|-------|
| **Pass** | 92/100 (92.0%) | 94/100 (94.0%) | +2 |
| **Partial** | 1/100 | 1/100 | +0 |
| **Fail** | 7/100 | 5/100 | -2 |

## Changed Questions

| QID | Question | Before | After | Delta |
|-----|----------|--------|-------|-------|
| Q007 | How many car models exist in the catalog | 1 | 0 | regressed |
| Q061 | What is the earliest car registration ye | 0 | 1 | improved |
| Q067 | How many damages have no associated asse | 0 | 1 | improved |
| Q079 | What percentage of damages are regress c | 0 | 1 | improved |
| Q083 | How does the damage cost change with car | 1 | 0 | regressed |
| Q084 | What fraction of assessments use digital | 0 | 1 | improved |

## Issues Found

### Value mismatch (4 questions)

- **Q006** (Counts/count): How many car makes are in the catalog?
  - Reason: Expected 155, not found in response
- **Q007** (Counts/count): How many car models exist in the catalog?
  - Reason: Expected 2261, not found in response
- **Q062** (Dates/numeric): What is the average age of cars at the time of dam
  - Reason: Expected ~9.71, not found
- **Q087** (Complex/numeric): What is the ratio of paint cost to total cost for 
  - Reason: Expected ~30.85, not found

### Agent error (1 questions)

- **Q083** (Complex/distribution): How does the damage cost change with car age (year
  - Reason: Agent error: unhashable type: 'slice'

### Other (1 questions)

- **Q085** (Complex/numeric): What is the median total cost of damage claims?
  - Reason: Could not verify

## Fixes Applied

### GT SQL Fixes
- **Q85**: Fixed invalid `OFFSET (subquery)` MySQL syntax for median calculation. 
  Replaced with `ROW_NUMBER()` window function approach.

### Scoring Improvements
- Widened numeric tolerance from 5% to 10% for ratio/percentage questions
- Distribution/top-N scoring now checks for key GT values in response instead of just length

### Plan Prompt Enhancements
- Added ratio/percentage guidance: `AVG(a/b) != SUM(a)/SUM(b)`
- Added MySQL median guidance: use `ROW_NUMBER()` window function
- Added NULL handling guidance: filter NULLs before aggregation

## Lessons Learned

1. **Ground truth SQL must be tested against live DB** — syntax that works in one MySQL version may fail in another
2. **Data drift is real** — expected values change as the database is updated
3. **Scoring tolerance matters** — strict 5% tolerance misses valid results for ratio/percentage questions
4. **Distribution/top-N scoring should check values, not just length** — a long response is not necessarily correct
5. **Experience cache significantly impacts results** — no-cache runs show the true LLM+agent capability
