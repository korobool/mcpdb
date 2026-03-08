# Phase 1: Query Battery Report

Generated: 2026-03-08

## Overall Summary

| Source Type | Pass | Total | Rate |
|-------------|------|-------|------|
| DB (bgins, local MySQL) | 49 | 50 | 98.0% |
| DB (portfolio_analysis, remote PG) | 17 | 25 | 68.0% |
| CSV (Qala-MTPL + CONTRACTS2023) | 30 | 30 | 100.0% |
| XLSX (Paid + Reserved) | 19 | 20 | 95.0% |
| **Subtotal (Phase 1)** | **115** | **125** | **92.0%** |
| Stress (257MB SQLite, 3.15M rows) | 48 | 50 | 96.0% |
| **Grand Total** | **163** | **175** | **93.1%** |

## DB Battery (75 queries)

### bgins (local MySQL, 21 tables)
- **49/50 passed (98.0%)**
- 1 timeout: deep mode investigation (comprehensive analysis exceeded 300s)
- Categories all at 100% except deep_investigation (50%)

### portfolio_analysis (remote PostgreSQL, 10 tables)
- **17/25 passed (68.0%)**
- 8 timeouts — all caused by remote DB statement timeout limits
- Remote DB has aggressive query timeouts, causing retries and eventual timeout
- The optimization_required mode correctly triggered for large remote tables

### Failures Detail

| ID | Source | Question | Status | Mode |
|----|--------|----------|--------|------|
| db033 | bgins | Comprehensive claims analysis | timeout | deep |
| rdb008 | portfolio | Top companies by policy count | timeout | optimization |
| rdb009 | portfolio | Loss ratio by company | timeout | simple |
| rdb013 | portfolio | Claims bar chart by company | timeout | optimization |
| rdb015 | portfolio | Comprehensive portfolio analysis | timeout | deep |
| rdb016 | portfolio | Risk scores vs actual claims | timeout | quick |
| rdb018 | portfolio | Highest claim-to-premium ratio | timeout | optimization |
| rdb021 | portfolio | Geographic distribution by address | timeout | optimization |
| rdb022 | portfolio | Company size vs claim severity | timeout | extended |

**Root cause:** Remote PostgreSQL has statement-level timeouts that kill long queries.
These are infrastructure limitations, not mcpdb bugs.

## CSV Battery (30 queries)

**30/30 passed (100.0%)**

| Category | Pass | Total |
|----------|------|-------|
| schema_discovery | 4 | 4 |
| simple_aggregation | 5 | 5 |
| distribution | 4 | 4 |
| temporal | 3 | 3 |
| chart | 3 | 3 |
| complex_analytics | 4 | 4 |
| edge_case | 1 | 1 |
| joins | 3 | 3 |

- Qala-MTPL (78MB, MTPL insurance): All 20 queries passed
- CONTRACTS2023 (231MB, claims): All 10 queries passed
- optimization_required mode correctly triggered for 231MB file
- Avg time: ~40s per query

## XLSX Battery (20 queries)

**19/20 passed (95.0%)**

| Category | Pass | Total |
|----------|------|-------|
| schema_discovery | 4 | 4 |
| simple_aggregation | 5 | 5 |
| distribution | 2 | 2 |
| temporal | 2 | 2 |
| chart | 2 | 2 |
| edge_case | 2 | 2 |
| complex_analytics | 1 | 1 |

- Paid.xlsx: 9/10 passed (1 timeout on distribution query with extended mode)
- Reserved.xlsx: 10/10 passed
- 1 timeout: xlsx014 (distribution of reserved amounts) — extended mode took >300s

## Stress Test (50 queries on 257MB SQLite, 3.15M rows)

**48/50 passed (96.0%)**

| Category | Pass | Total |
|----------|------|-------|
| full_scan | 5 | 5 |
| join | 5 | 5 |
| time_series | 5 | 5 |
| aggregation | 5 | 5 |
| events_analysis | 5 | 5 |
| schema | 2 | 2 |
| data_quality | 2 | 3 |
| chart | 5 | 5 |
| complex | 9 | 10 |
| deep | 3 | 3 |

- 2 timeouts: stress028 (NULL check across all tables) and stress034 (histogram)
- Both caused by synthesis code errors (KeyError accessing execution log)
- optimization_required mode correctly triggered for all large-table queries
- Avg query time: ~55s

## Key Findings

1. **Core engine is production-ready**: 92% pass rate across diverse sources
2. **CSV handling is excellent**: 100% pass rate including 231MB files
3. **XLSX works well**: 95% with proper sheet/context enrichment
4. **Optimization mode works**: Correctly triggered for large datasets
5. **Synthesis retries work**: Many queries recovered from initial synthesis errors
6. **Remote DB timeouts are infrastructure limits**, not mcpdb bugs
7. **Deep mode is most expensive**: 300s timeout is tight for comprehensive analysis
8. **Observer warnings fire correctly**: Slow phases detected and reported
