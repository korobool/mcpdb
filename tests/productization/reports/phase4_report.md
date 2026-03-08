# Phase 4: Large Database Stress Test Report

Generated: 2026-03-08T15:46:35.729646

Database: /home/olek/workspace/mcpdb/tests/productization/large_db/stress_test.db (257.4 MB)

## Summary

**Overall: 48/50 (96.0%)**

- Pass: 48
- Fail: 0
- Error: 0
- Timeout: 2

**Timing:** avg=77.8s, max=432.4s, total=3892s
**Step timing:** avg_max_step=2121ms, absolute_max=9407ms

## By Category

| Category | Pass | Fail | Error | Timeout | Avg Time |
|----------|------|------|-------|---------|----------|
| aggregation | 5 | 0 | 0 | 0 | 46.0s |
| chart | 4 | 0 | 0 | 1 | 130.2s |
| complex | 12 | 0 | 0 | 0 | 90.1s |
| data_quality | 3 | 0 | 0 | 0 | 94.6s |
| deep | 2 | 0 | 0 | 1 | 244.8s |
| events_analysis | 5 | 0 | 0 | 0 | 46.0s |
| full_scan | 5 | 0 | 0 | 0 | 45.8s |
| join | 5 | 0 | 0 | 0 | 43.4s |
| schema | 2 | 0 | 0 | 0 | 6.7s |
| time_series | 5 | 0 | 0 | 0 | 44.2s |

## Failures

- **stress033** [timeout]: Create a scatter plot of customer age vs total spending
  - Error: Timed out after 300s
  - Mode: , Time: 432.4s
- **stress036** [timeout]: Perform a comprehensive business analysis: revenue trends, c
  - Error: Timed out after 300s
  - Mode: , Time: 300.0s

## Slow Queries (>120s)

- **stress028**: 228.3s — Are there any NULL values in critical columns across all tab
- **stress033**: 432.4s — Create a scatter plot of customer age vs total spending
- **stress036**: 300.0s — Perform a comprehensive business analysis: revenue trends, c
- **stress037**: 293.5s — Investigate the factors that drive high-value transactions
- **stress038**: 182.8s — Which customers are at risk of churning based on their trans
- **stress040**: 134.7s — Show the market basket analysis - which products are frequen
- **stress044**: 159.8s — Compare the performance of different payment methods over ti
- **stress050**: 140.9s — Create a comprehensive dashboard with KPIs: total revenue, a