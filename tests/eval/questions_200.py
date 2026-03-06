"""Extended 200-question eval suite (Q101-Q300) for bgins database.

Inspired by motor claims playbook SQL templates, data quality checks,
and actuarial analysis patterns. All SQL is MySQL 8.0 compatible.
"""

from __future__ import annotations

# Common CTE snippets (for documentation only, each SQL is self-contained)
# latest_mc: SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id
# latest_est: same but grouped by opis_id, type (for both mc and n24)
# part_resolve: COALESCE(pi.part_name, pf.part_name) with LEFT JOINs on range

QUESTIONS_200 = [
    # ======================================================================
    # Cat 1: Frequency & Trend Analysis (Q101-Q120)
    # ======================================================================
    {
        "id": 101,
        "q": "How many claims were opened per month? Show month and count.",
        "sql": "SELECT DATE_FORMAT(o.opis_date, '%Y-%m') AS month, COUNT(*) AS claims FROM ins_opis o GROUP BY month ORDER BY month",
        "type": "distribution",
    },
    {
        "id": 102,
        "q": "How many claims were opened per quarter? Show year, quarter, and count.",
        "sql": "SELECT YEAR(o.opis_date) AS yr, QUARTER(o.opis_date) AS qtr, COUNT(*) AS claims FROM ins_opis o WHERE o.opis_date IS NOT NULL GROUP BY yr, qtr ORDER BY yr, qtr",
        "type": "distribution",
    },
    {
        "id": 103,
        "q": "How many claims were opened per year?",
        "sql": "SELECT YEAR(o.opis_date) AS yr, COUNT(*) AS claims FROM ins_opis o WHERE o.opis_date IS NOT NULL GROUP BY yr ORDER BY yr",
        "type": "distribution",
    },
    {
        "id": 104,
        "q": "How many claims exist for each damage type (damage_typeid)?",
        "sql": "SELECT d.damage_typeid, COUNT(*) AS claims FROM ins_opis o JOIN ins_damages d ON d.damage_id = o.damage_id GROUP BY d.damage_typeid ORDER BY claims DESC",
        "type": "distribution",
    },
    {
        "id": 105,
        "q": "How many claims exist for each claim_type?",
        "sql": "SELECT claim_type, COUNT(*) AS claims FROM ins_opis GROUP BY claim_type ORDER BY claims DESC",
        "type": "distribution",
    },
    {
        "id": 106,
        "q": "How many damage events occurred on each day of the week?",
        "sql": "SELECT DAYOFWEEK(damage_date) AS dow, COUNT(*) AS cnt FROM ins_damages WHERE damage_date IS NOT NULL GROUP BY dow ORDER BY dow",
        "type": "distribution",
    },
    {
        "id": 107,
        "q": "What is the seasonal pattern of damage events by month of year?",
        "sql": "SELECT MONTH(damage_date) AS m, COUNT(*) AS cnt FROM ins_damages WHERE damage_date IS NOT NULL GROUP BY m ORDER BY m",
        "type": "distribution",
    },
    {
        "id": 108,
        "q": "What is the average filing lag in days between the damage date and the claim filing date (opis_date)?",
        "sql": "SELECT AVG(DATEDIFF(o.opis_date, d.damage_date)) AS avg_lag_days FROM ins_opis o JOIN ins_damages d ON d.damage_id = o.damage_id WHERE d.damage_date IS NOT NULL AND o.opis_date IS NOT NULL",
        "type": "numeric",
    },
    {
        "id": 109,
        "q": "What is the year-over-year growth in claim count? Show each year and the count.",
        "sql": "SELECT YEAR(opis_date) AS yr, COUNT(*) AS claims FROM ins_opis WHERE opis_date IS NOT NULL GROUP BY yr ORDER BY yr",
        "type": "distribution",
    },
    {
        "id": 110,
        "q": "How many claims were opened per month in 2023?",
        "sql": "SELECT MONTH(opis_date) AS m, COUNT(*) AS claims FROM ins_opis WHERE YEAR(opis_date) = 2023 GROUP BY m ORDER BY m",
        "type": "distribution",
    },
    {
        "id": 111,
        "q": "How many claims were opened per quarter in 2024?",
        "sql": "SELECT QUARTER(opis_date) AS qtr, COUNT(*) AS claims FROM ins_opis WHERE YEAR(opis_date) = 2024 GROUP BY qtr ORDER BY qtr",
        "type": "distribution",
    },
    {
        "id": 112,
        "q": "How many claims per damage_typeid were there in each year?",
        "sql": "SELECT YEAR(d.damage_date) AS yr, d.damage_typeid, COUNT(*) AS claims FROM ins_opis o JOIN ins_damages d ON d.damage_id = o.damage_id WHERE d.damage_date IS NOT NULL GROUP BY yr, d.damage_typeid ORDER BY yr, d.damage_typeid",
        "type": "distribution",
    },
    {
        "id": 113,
        "q": "What is the average number of claims per day across the entire dataset?",
        "sql": "SELECT COUNT(*) / DATEDIFF(MAX(opis_date), MIN(opis_date)) AS avg_claims_per_day FROM ins_opis WHERE opis_date IS NOT NULL",
        "type": "numeric",
    },
    {
        "id": 114,
        "q": "How many claims were filed within 7 days of the damage event?",
        "sql": "SELECT COUNT(*) FROM ins_opis o JOIN ins_damages d ON d.damage_id = o.damage_id WHERE d.damage_date IS NOT NULL AND o.opis_date IS NOT NULL AND DATEDIFF(o.opis_date, d.damage_date) <= 7",
        "type": "count",
    },
    {
        "id": 115,
        "q": "How many claims were filed more than 30 days after the damage event?",
        "sql": "SELECT COUNT(*) FROM ins_opis o JOIN ins_damages d ON d.damage_id = o.damage_id WHERE d.damage_date IS NOT NULL AND o.opis_date IS NOT NULL AND DATEDIFF(o.opis_date, d.damage_date) > 30",
        "type": "count",
    },
    {
        "id": 116,
        "q": "How many claims with a non-zero total cost were filed per month?",
        "sql": "SELECT DATE_FORMAT(o.opis_date, '%Y-%m') AS month, COUNT(*) AS claims FROM ins_opis o JOIN ins_damages d ON d.damage_id = o.damage_id WHERE d.total_cost > 0 AND o.opis_date IS NOT NULL GROUP BY month ORDER BY month",
        "type": "distribution",
    },
    {
        "id": 117,
        "q": "How many claims with damage_typeid = 0 were there per year?",
        "sql": "SELECT YEAR(d.damage_date) AS yr, COUNT(*) AS claims FROM ins_opis o JOIN ins_damages d ON d.damage_id = o.damage_id WHERE d.damage_typeid = 0 AND d.damage_date IS NOT NULL GROUP BY yr ORDER BY yr",
        "type": "distribution",
    },
    {
        "id": 118,
        "q": "What is the distribution of claims per car? How many cars have 1 claim, 2 claims, 3 or more?",
        "sql": "SELECT claims_per_car, COUNT(*) AS car_count FROM (SELECT car_id, COUNT(*) AS claims_per_car FROM ins_opis GROUP BY car_id) t GROUP BY claims_per_car ORDER BY claims_per_car",
        "type": "distribution",
    },
    {
        "id": 119,
        "q": "How many claims were opened per month in 2025?",
        "sql": "SELECT MONTH(opis_date) AS m, COUNT(*) AS claims FROM ins_opis WHERE YEAR(opis_date) = 2025 GROUP BY m ORDER BY m",
        "type": "distribution",
    },
    {
        "id": 120,
        "q": "What is the distribution of claim filing hour of day (from opis_date)?",
        "sql": "SELECT HOUR(opis_date) AS hr, COUNT(*) AS cnt FROM ins_opis WHERE opis_date IS NOT NULL GROUP BY hr ORDER BY hr",
        "type": "distribution",
    },

    # ======================================================================
    # Cat 2: Cost Severity & Structure (Q121-Q145)
    # ======================================================================
    {
        "id": 121,
        "q": "What is the average MC estimated total cost by car brand?",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id) SELECT b.brand_name, AVG(mc.total_cost) AS avg_cost, COUNT(*) AS claims FROM latest_mc mc JOIN ins_opis o ON o.opis_id=mc.opis_id JOIN ins_cars c ON c.car_id=o.car_id JOIN srv_mc_horizon_brand b ON c.car_mc_brand=b.brand_id GROUP BY b.brand_name ORDER BY avg_cost DESC",
        "type": "distribution",
    },
    {
        "id": 122,
        "q": "What is the average MC estimated total cost by damage type?",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id) SELECT d.damage_typeid, AVG(mc.total_cost) AS avg_cost, COUNT(*) AS claims FROM latest_mc mc JOIN ins_opis o ON o.opis_id=mc.opis_id JOIN ins_damages d ON d.damage_id=o.damage_id GROUP BY d.damage_typeid ORDER BY avg_cost DESC",
        "type": "distribution",
    },
    {
        "id": 123,
        "q": "What is the MC estimate cost structure? Show the average share of parts, repairs, mounts, paints, and other costs as percentages of total.",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id) SELECT ROUND(100*AVG(newparts_cost/NULLIF(total_cost,0)),2) AS pct_parts, ROUND(100*AVG(repairs_cost/NULLIF(total_cost,0)),2) AS pct_repairs, ROUND(100*AVG(mounts_cost/NULLIF(total_cost,0)),2) AS pct_mounts, ROUND(100*AVG(paints_cost/NULLIF(total_cost,0)),2) AS pct_paints, ROUND(100*AVG(other_cost/NULLIF(total_cost,0)),2) AS pct_other FROM latest_mc WHERE total_cost > 0",
        "type": "distribution",
    },
    {
        "id": 124,
        "q": "How many claims have a latest MC estimate above 5000 BGN?",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id) SELECT COUNT(*) FROM latest_mc WHERE total_cost >= 5000",
        "type": "count",
    },
    {
        "id": 125,
        "q": "How many claims have a latest MC estimate above 10000 BGN?",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id) SELECT COUNT(*) FROM latest_mc WHERE total_cost >= 10000",
        "type": "count",
    },
    {
        "id": 126,
        "q": "What is the average parts cost share (newparts_cost / total_cost) from latest MC estimates?",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id) SELECT ROUND(100*AVG(newparts_cost/NULLIF(total_cost,0)),2) AS avg_parts_share_pct FROM latest_mc WHERE total_cost > 0",
        "type": "numeric",
    },
    {
        "id": 127,
        "q": "What is the average paint cost share (paints_cost / total_cost) from latest MC estimates?",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id) SELECT ROUND(100*AVG(paints_cost/NULLIF(total_cost,0)),2) AS avg_paint_share_pct FROM latest_mc WHERE total_cost > 0",
        "type": "numeric",
    },
    {
        "id": 128,
        "q": "How many claims are 'paint heavy' (paint share > 40% of total MC estimate cost)?",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id) SELECT COUNT(*) FROM latest_mc WHERE total_cost > 0 AND paints_cost/NULLIF(total_cost,0) > 0.4",
        "type": "count",
    },
    {
        "id": 129,
        "q": "How many claims are 'parts heavy' (parts share > 60% of total MC estimate cost)?",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id) SELECT COUNT(*) FROM latest_mc WHERE total_cost > 0 AND newparts_cost/NULLIF(total_cost,0) > 0.6",
        "type": "count",
    },
    {
        "id": 130,
        "q": "What is the average MC estimated cost by car year group?",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id) SELECT d.car_yeargroup, AVG(mc.total_cost) AS avg_cost, COUNT(*) AS claims FROM latest_mc mc JOIN ins_opis o ON o.opis_id=mc.opis_id JOIN ins_damages d ON d.damage_id=o.damage_id GROUP BY d.car_yeargroup ORDER BY d.car_yeargroup",
        "type": "distribution",
    },
    {
        "id": 131,
        "q": "What is the average MC estimated cost by claim type?",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id) SELECT o.claim_type, AVG(mc.total_cost) AS avg_cost, COUNT(*) AS claims FROM latest_mc mc JOIN ins_opis o ON o.opis_id=mc.opis_id GROUP BY o.claim_type ORDER BY avg_cost DESC",
        "type": "distribution",
    },
    {
        "id": 132,
        "q": "Which top 5 car brands have the highest average MC estimated cost?",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id) SELECT b.brand_name, AVG(mc.total_cost) AS avg_cost, COUNT(*) AS claims FROM latest_mc mc JOIN ins_opis o ON o.opis_id=mc.opis_id JOIN ins_cars c ON c.car_id=o.car_id JOIN srv_mc_horizon_brand b ON c.car_mc_brand=b.brand_id GROUP BY b.brand_name HAVING claims >= 3 ORDER BY avg_cost DESC LIMIT 5",
        "type": "top_n",
    },
    {
        "id": 133,
        "q": "What is the average repair labor hours from latest MC estimates?",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id) SELECT AVG(repairs_hours) AS avg_repair_hours FROM latest_mc",
        "type": "numeric",
    },
    {
        "id": 134,
        "q": "What is the average total labor hours (repair + mount + paint) from latest MC estimates?",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id) SELECT AVG(repairs_hours + mounts_hours + paints_hours) AS avg_total_hours FROM latest_mc",
        "type": "numeric",
    },
    {
        "id": 135,
        "q": "What is the average MC estimated total cost by year of claim?",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id) SELECT YEAR(o.opis_date) AS yr, AVG(mc.total_cost) AS avg_cost, COUNT(*) AS claims FROM latest_mc mc JOIN ins_opis o ON o.opis_id=mc.opis_id WHERE o.opis_date IS NOT NULL GROUP BY yr ORDER BY yr",
        "type": "distribution",
    },
    {
        "id": 136,
        "q": "What is the average mount cost share from latest MC estimates?",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id) SELECT ROUND(100*AVG(mounts_cost/NULLIF(total_cost,0)),2) AS avg_mount_share_pct FROM latest_mc WHERE total_cost > 0",
        "type": "numeric",
    },
    {
        "id": 137,
        "q": "What is the average MC estimated total cost grouped by number of damage lines per claim?",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id), dmg_lines AS (SELECT opis_id, COUNT(*) AS damage_lines FROM ins_opis_rows GROUP BY opis_id) SELECT l.damage_lines, AVG(mc.total_cost) AS avg_cost, COUNT(*) AS claims FROM latest_mc mc JOIN dmg_lines l ON l.opis_id=mc.opis_id GROUP BY l.damage_lines ORDER BY l.damage_lines",
        "type": "distribution",
    },
    {
        "id": 138,
        "q": "What is the average overall discount (service_discall) from latest MC estimates?",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id) SELECT AVG(service_discall) AS avg_discount FROM latest_mc WHERE total_cost > 0",
        "type": "numeric",
    },
    {
        "id": 139,
        "q": "What is the distribution of MC estimated total cost by range (0-1000, 1000-3000, 3000-5000, 5000-10000, 10000+)?",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id) SELECT CASE WHEN total_cost < 1000 THEN '0-1000' WHEN total_cost < 3000 THEN '1000-3000' WHEN total_cost < 5000 THEN '3000-5000' WHEN total_cost < 10000 THEN '5000-10000' ELSE '10000+' END AS cost_range, COUNT(*) AS claims FROM latest_mc GROUP BY cost_range ORDER BY MIN(total_cost)",
        "type": "distribution",
    },
    {
        "id": 140,
        "q": "How does the average latest MC estimated cost compare to the average damage total_cost?",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id) SELECT AVG(mc.total_cost) AS avg_mc_estimate, AVG(d.total_cost) AS avg_damage_total FROM latest_mc mc JOIN ins_opis o ON o.opis_id=mc.opis_id JOIN ins_damages d ON d.damage_id=o.damage_id",
        "type": "comparison",
    },
    {
        "id": 141,
        "q": "What is the average VAT sum from latest MC estimates?",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id) SELECT AVG(vat_sum) AS avg_vat_sum FROM latest_mc",
        "type": "numeric",
    },
    {
        "id": 142,
        "q": "How many latest MC estimates have a total cost of zero?",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id) SELECT COUNT(*) FROM latest_mc WHERE total_cost = 0",
        "type": "count",
    },
    {
        "id": 143,
        "q": "What is the 90th percentile (P90) of MC estimated total cost?",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id), ranked AS (SELECT total_cost, ROW_NUMBER() OVER (ORDER BY total_cost) AS rn, COUNT(*) OVER() AS cnt FROM latest_mc WHERE total_cost > 0) SELECT total_cost AS p90_cost FROM ranked WHERE rn = CEIL(0.9 * cnt) LIMIT 1",
        "type": "numeric",
    },
    {
        "id": 144,
        "q": "What is the average MC estimated cost for claims that have at least one major repair (part_repair=3)?",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id), major AS (SELECT DISTINCT opis_id FROM ins_opis_rows WHERE part_repair=3) SELECT AVG(mc.total_cost) AS avg_cost FROM latest_mc mc JOIN major m ON m.opis_id=mc.opis_id",
        "type": "numeric",
    },
    {
        "id": 145,
        "q": "What is the average 'other cost' from latest MC estimates?",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id) SELECT AVG(other_cost) AS avg_other_cost FROM latest_mc",
        "type": "numeric",
    },

    # ======================================================================
    # Cat 3: Damage & Parts Patterns (Q146-Q165)
    # ======================================================================
    {
        "id": 146,
        "q": "What are the top 10 most frequently damaged parts? Resolve part names across catalogs.",
        "sql": "SELECT COALESCE(pi.part_name, pf.part_name) AS part_name, SUM(r.quantity) AS qty FROM ins_opis_rows r LEFT JOIN ins_partsindex pi ON r.part_id=pi.part_id AND r.part_id < 10000000 LEFT JOIN ins_partsfree pf ON r.part_id=pf.part_id AND r.part_id >= 20000000 GROUP BY part_name ORDER BY qty DESC LIMIT 10",
        "type": "top_n",
    },
    {
        "id": 147,
        "q": "What is the parts catalog source distribution? How many opis_rows come from SmartClaiMS (part_id < 10M) vs free text parts (part_id >= 20M)?",
        "sql": "SELECT CASE WHEN part_id < 10000000 THEN 'SmartClaiMS' WHEN part_id >= 10000000 AND part_id < 20000000 THEN 'MultiCat' ELSE 'Free' END AS catalog, COUNT(*) AS cnt FROM ins_opis_rows GROUP BY catalog ORDER BY cnt DESC",
        "type": "distribution",
    },
    {
        "id": 148,
        "q": "What is the total count of replacement lines (part_new IN (1,2)) vs repair lines (part_repair IN (1,2,3)) in assessments?",
        "sql": "SELECT SUM(CASE WHEN part_new IN (1,2) THEN 1 ELSE 0 END) AS replace_lines, SUM(CASE WHEN part_repair IN (1,2,3) THEN 1 ELSE 0 END) AS repair_lines, COUNT(*) AS total_lines FROM ins_opis_rows",
        "type": "comparison",
    },
    {
        "id": 149,
        "q": "What is the repair severity distribution? Show counts for part_repair values 0, 1, 2, 3.",
        "sql": "SELECT part_repair, COUNT(*) AS cnt FROM ins_opis_rows GROUP BY part_repair ORDER BY part_repair",
        "type": "distribution",
    },
    {
        "id": 150,
        "q": "What is the average number of damaged items (opis_rows) per claim?",
        "sql": "SELECT AVG(lines_per_claim) AS avg_lines FROM (SELECT opis_id, COUNT(*) AS lines_per_claim FROM ins_opis_rows GROUP BY opis_id) t",
        "type": "numeric",
    },
    {
        "id": 151,
        "q": "How many claims have exactly 1 damaged part?",
        "sql": "SELECT COUNT(*) FROM (SELECT opis_id FROM ins_opis_rows GROUP BY opis_id HAVING COUNT(*)=1) t",
        "type": "count",
    },
    {
        "id": 152,
        "q": "How many claims have more than 10 damaged parts?",
        "sql": "SELECT COUNT(*) FROM (SELECT opis_id FROM ins_opis_rows GROUP BY opis_id HAVING COUNT(*)>10) t",
        "type": "count",
    },
    {
        "id": 153,
        "q": "What are the top 5 parts most frequently replaced (part_new=1)? Show resolved part names.",
        "sql": "SELECT COALESCE(pi.part_name, pf.part_name) AS part_name, COUNT(*) AS cnt FROM ins_opis_rows r LEFT JOIN ins_partsindex pi ON r.part_id=pi.part_id AND r.part_id < 10000000 LEFT JOIN ins_partsfree pf ON r.part_id=pf.part_id AND r.part_id >= 20000000 WHERE r.part_new=1 GROUP BY part_name ORDER BY cnt DESC LIMIT 5",
        "type": "top_n",
    },
    {
        "id": 154,
        "q": "What are the top 5 most frequently painted parts (part_paint=1)?",
        "sql": "SELECT COALESCE(pi.part_name, pf.part_name) AS part_name, COUNT(*) AS cnt FROM ins_opis_rows r LEFT JOIN ins_partsindex pi ON r.part_id=pi.part_id AND r.part_id < 10000000 LEFT JOIN ins_partsfree pf ON r.part_id=pf.part_id AND r.part_id >= 20000000 WHERE r.part_paint=1 GROUP BY part_name ORDER BY cnt DESC LIMIT 5",
        "type": "top_n",
    },
    {
        "id": 155,
        "q": "How many parts appear in both a replacement role (part_new=1) and a repair role (part_repair>0) across different claims?",
        "sql": "SELECT COUNT(*) FROM (SELECT part_id FROM ins_opis_rows WHERE part_new=1 GROUP BY part_id) rep INNER JOIN (SELECT part_id FROM ins_opis_rows WHERE part_repair > 0 GROUP BY part_id) rpr ON rep.part_id=rpr.part_id",
        "type": "count",
    },
    {
        "id": 156,
        "q": "What is the average quantity per opis_row?",
        "sql": "SELECT AVG(quantity) FROM ins_opis_rows",
        "type": "numeric",
    },
    {
        "id": 157,
        "q": "What are the top 5 parts by major repair count (part_repair=3)?",
        "sql": "SELECT COALESCE(pi.part_name, pf.part_name) AS part_name, COUNT(*) AS cnt FROM ins_opis_rows r LEFT JOIN ins_partsindex pi ON r.part_id=pi.part_id AND r.part_id < 10000000 LEFT JOIN ins_partsfree pf ON r.part_id=pf.part_id AND r.part_id >= 20000000 WHERE r.part_repair=3 GROUP BY part_name ORDER BY cnt DESC LIMIT 5",
        "type": "top_n",
    },
    {
        "id": 158,
        "q": "What percentage of opis_rows have part_paint=1?",
        "sql": "SELECT ROUND(100.0 * SUM(CASE WHEN part_paint=1 THEN 1 ELSE 0 END) / COUNT(*), 2) AS paint_pct FROM ins_opis_rows",
        "type": "numeric",
    },
    {
        "id": 159,
        "q": "What is the paint frequency (share of lines with part_paint=1) by car brand?",
        "sql": "SELECT b.brand_name, AVG(CASE WHEN r.part_paint=1 THEN 1.0 ELSE 0.0 END) AS paint_share, COUNT(*) AS damage_lines FROM ins_opis_rows r JOIN ins_opis o ON o.opis_id=r.opis_id JOIN ins_cars c ON c.car_id=o.car_id JOIN srv_mc_horizon_brand b ON c.car_mc_brand=b.brand_id GROUP BY b.brand_name ORDER BY paint_share DESC",
        "type": "distribution",
    },
    {
        "id": 160,
        "q": "What is the average number of paint lines (part_paint=1) per claim?",
        "sql": "SELECT AVG(paint_lines) FROM (SELECT opis_id, SUM(CASE WHEN part_paint=1 THEN 1 ELSE 0 END) AS paint_lines FROM ins_opis_rows GROUP BY opis_id) t",
        "type": "numeric",
    },
    {
        "id": 161,
        "q": "What is the distribution of damage line counts per claim? Show how many claims have 1-3, 4-6, 7-10, and 10+ damage lines.",
        "sql": "SELECT CASE WHEN cnt <= 3 THEN '1-3' WHEN cnt <= 6 THEN '4-6' WHEN cnt <= 10 THEN '7-10' ELSE '10+' END AS line_group, COUNT(*) AS claims FROM (SELECT opis_id, COUNT(*) AS cnt FROM ins_opis_rows GROUP BY opis_id) t GROUP BY line_group ORDER BY MIN(cnt)",
        "type": "distribution",
    },
    {
        "id": 162,
        "q": "How many distinct parts are always replaced (part_new=1 in all occurrences, never repaired)?",
        "sql": "SELECT COUNT(*) FROM (SELECT part_id FROM ins_opis_rows GROUP BY part_id HAVING SUM(CASE WHEN part_new=1 THEN 1 ELSE 0 END) = COUNT(*) AND SUM(CASE WHEN part_repair > 0 THEN 1 ELSE 0 END) = 0) t",
        "type": "count",
    },
    {
        "id": 163,
        "q": "Which parts have the highest ratio of major repairs (part_repair=3) to total occurrences? Show top 5 with at least 5 occurrences.",
        "sql": "SELECT COALESCE(pi.part_name, pf.part_name) AS part_name, SUM(CASE WHEN r.part_repair=3 THEN 1 ELSE 0 END) / COUNT(*) AS major_ratio, COUNT(*) AS total FROM ins_opis_rows r LEFT JOIN ins_partsindex pi ON r.part_id=pi.part_id AND r.part_id < 10000000 LEFT JOIN ins_partsfree pf ON r.part_id=pf.part_id AND r.part_id >= 20000000 GROUP BY part_name HAVING total >= 5 ORDER BY major_ratio DESC LIMIT 5",
        "type": "top_n",
    },
    {
        "id": 164,
        "q": "How many claims have all parts replaced (part_new=1) and no repairs (part_repair=0 for all lines)?",
        "sql": "SELECT COUNT(*) FROM (SELECT opis_id FROM ins_opis_rows GROUP BY opis_id HAVING MIN(part_new) = 1 AND MAX(part_repair) = 0) t",
        "type": "count",
    },
    {
        "id": 165,
        "q": "How many opis_rows have quantity greater than 1?",
        "sql": "SELECT COUNT(*) FROM ins_opis_rows WHERE quantity > 1",
        "type": "count",
    },

    # ======================================================================
    # Cat 4: Supplier & Expense Analysis (Q166-Q185)
    # ======================================================================
    {
        "id": 166,
        "q": "What are the top 10 suppliers by total expense value (value_vat)?",
        "sql": "SELECT supplier_name, SUM(value_vat) AS total_value, COUNT(*) AS line_cnt FROM ins_mc_invexpenses WHERE supplier_name IS NOT NULL AND supplier_name != '' GROUP BY supplier_name ORDER BY total_value DESC LIMIT 10",
        "type": "top_n",
    },
    {
        "id": 167,
        "q": "What are the top 10 suppliers by number of expense lines?",
        "sql": "SELECT supplier_name, COUNT(*) AS line_cnt FROM ins_mc_invexpenses WHERE supplier_name IS NOT NULL AND supplier_name != '' GROUP BY supplier_name ORDER BY line_cnt DESC LIMIT 10",
        "type": "top_n",
    },
    {
        "id": 168,
        "q": "What is the average expense line value (value_vat) overall?",
        "sql": "SELECT AVG(value_vat) FROM ins_mc_invexpenses",
        "type": "numeric",
    },
    {
        "id": 169,
        "q": "What is the expense subtype distribution? Show counts and total value for each expense_subtype.",
        "sql": "SELECT expense_subtype, COUNT(*) AS line_cnt, SUM(value_vat) AS total_value FROM ins_mc_invexpenses GROUP BY expense_subtype ORDER BY total_value DESC",
        "type": "distribution",
    },
    {
        "id": 170,
        "q": "What share of expense value comes from 'unlinked' expenses (item_id=0, document-level expenses)?",
        "sql": "SELECT ROUND(100.0 * SUM(CASE WHEN item_id=0 THEN value_vat ELSE 0 END) / SUM(value_vat), 2) AS unlinked_pct FROM ins_mc_invexpenses WHERE value_vat IS NOT NULL",
        "type": "numeric",
    },
    {
        "id": 171,
        "q": "What is the average number of expense lines per MC estimate?",
        "sql": "WITH latest_mc AS (SELECT ic.invcalc_id FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id) SELECT AVG(cnt) FROM (SELECT mc.invcalc_id, COUNT(e.expense_id) AS cnt FROM latest_mc mc LEFT JOIN ins_mc_invexpenses e ON e.doc_id=mc.invcalc_id GROUP BY mc.invcalc_id) t",
        "type": "numeric",
    },
    {
        "id": 172,
        "q": "What are the top 10 most expensive individual expense names by total value?",
        "sql": "SELECT expense_name, SUM(value_vat) AS total_value, COUNT(*) AS line_cnt FROM ins_mc_invexpenses GROUP BY expense_name ORDER BY total_value DESC LIMIT 10",
        "type": "top_n",
    },
    {
        "id": 173,
        "q": "What is the expense distribution by expense type name? Join with inv_exptypes.",
        "sql": "SELECT t.et_name, SUM(e.value_vat) AS total_value, COUNT(*) AS line_cnt FROM ins_mc_invexpenses e LEFT JOIN inv_exptypes t ON t.exptype_id=e.expense_type GROUP BY t.et_name ORDER BY total_value DESC",
        "type": "distribution",
    },
    {
        "id": 174,
        "q": "What is the total expense value by unit type? Join with inv_expunits.",
        "sql": "SELECT u.unit_name, SUM(e.value_vat) AS total_value, COUNT(*) AS line_cnt FROM ins_mc_invexpenses e LEFT JOIN inv_expunits u ON u.unit_id=e.unit_id GROUP BY u.unit_name ORDER BY total_value DESC",
        "type": "distribution",
    },
    {
        "id": 175,
        "q": "What percentage of total expense value do the top 3 suppliers account for?",
        "sql": "SELECT ROUND(100.0 * SUM(top3.total_value) / (SELECT SUM(value_vat) FROM ins_mc_invexpenses WHERE supplier_name IS NOT NULL AND supplier_name != ''), 2) AS top3_pct FROM (SELECT supplier_name, SUM(value_vat) AS total_value FROM ins_mc_invexpenses WHERE supplier_name IS NOT NULL AND supplier_name != '' GROUP BY supplier_name ORDER BY total_value DESC LIMIT 3) top3",
        "type": "numeric",
    },
    {
        "id": 176,
        "q": "How many expense lines have a discount (discount_value > 0)?",
        "sql": "SELECT COUNT(*) FROM ins_mc_invexpenses WHERE discount_value > 0",
        "type": "count",
    },
    {
        "id": 177,
        "q": "What is the average final_price by expense type (joined with inv_exptypes)?",
        "sql": "SELECT t.et_name, AVG(e.final_price) AS avg_price FROM ins_mc_invexpenses e LEFT JOIN inv_exptypes t ON t.exptype_id=e.expense_type WHERE e.final_price > 0 GROUP BY t.et_name ORDER BY avg_price DESC",
        "type": "distribution",
    },
    {
        "id": 178,
        "q": "What is the total expense value for MC estimates only (not N24)?",
        "sql": "SELECT SUM(e.value_vat) AS total_mc_expense_value FROM ins_mc_invexpenses e INNER JOIN ins_mc_invcalc ic ON e.doc_id=ic.invcalc_id WHERE ic.type='mc'",
        "type": "numeric",
    },
    {
        "id": 179,
        "q": "What is the distribution of expense line counts per claim? Show how many claims have 1-10, 11-20, 21-50, 50+ expense lines.",
        "sql": "SELECT CASE WHEN cnt <= 10 THEN '1-10' WHEN cnt <= 20 THEN '11-20' WHEN cnt <= 50 THEN '21-50' ELSE '50+' END AS line_group, COUNT(*) AS claims FROM (SELECT doc_id, COUNT(*) AS cnt FROM ins_mc_invexpenses GROUP BY doc_id) t GROUP BY line_group ORDER BY MIN(cnt)",
        "type": "distribution",
    },
    {
        "id": 180,
        "q": "Which suppliers have the highest average expense line value? Show top 5 with at least 10 lines.",
        "sql": "SELECT supplier_name, AVG(value_vat) AS avg_value, COUNT(*) AS line_cnt FROM ins_mc_invexpenses WHERE supplier_name IS NOT NULL AND supplier_name != '' GROUP BY supplier_name HAVING line_cnt >= 10 ORDER BY avg_value DESC LIMIT 5",
        "type": "top_n",
    },
    {
        "id": 181,
        "q": "What is the total value of new parts expenses (expense_subtype=1)?",
        "sql": "SELECT SUM(value_vat) AS total_new_parts FROM ins_mc_invexpenses WHERE expense_subtype=1",
        "type": "numeric",
    },
    {
        "id": 182,
        "q": "How many expense lines have value_vat greater than 1000?",
        "sql": "SELECT COUNT(*) FROM ins_mc_invexpenses WHERE value_vat > 1000",
        "type": "count",
    },
    {
        "id": 183,
        "q": "What is the average total expense value per damage line for each claim?",
        "sql": "WITH claim_expenses AS (SELECT doc_id, SUM(value_vat) AS total_exp FROM ins_mc_invexpenses GROUP BY doc_id), claim_lines AS (SELECT ic.invcalc_id, COUNT(r.opis_rowid) AS damage_lines FROM ins_mc_invcalc ic JOIN ins_opis_rows r ON r.opis_id=ic.opis_id GROUP BY ic.invcalc_id) SELECT AVG(ce.total_exp / NULLIF(cl.damage_lines, 0)) AS avg_expense_per_line FROM claim_expenses ce JOIN claim_lines cl ON cl.invcalc_id=ce.doc_id",
        "type": "numeric",
    },
    {
        "id": 184,
        "q": "What is the total expense value by year (based on the estimate's opis_date)?",
        "sql": "SELECT YEAR(o.opis_date) AS yr, SUM(e.value_vat) AS total_value FROM ins_mc_invexpenses e JOIN ins_mc_invcalc ic ON e.doc_id=ic.invcalc_id JOIN ins_opis o ON o.opis_id=ic.opis_id WHERE o.opis_date IS NOT NULL GROUP BY yr ORDER BY yr",
        "type": "distribution",
    },
    {
        "id": 185,
        "q": "What is the total expense value for paint-related expense types (exptype_id=5)?",
        "sql": "SELECT SUM(e.value_vat) AS total_paint_expense FROM ins_mc_invexpenses e WHERE e.expense_type=5",
        "type": "numeric",
    },

    # ======================================================================
    # Cat 5: Repair Shop & Process (Q186-Q210)
    # ======================================================================
    {
        "id": 186,
        "q": "What are the top 10 repair shops (service_id) by number of claims?",
        "sql": "SELECT service_id, COUNT(*) AS claims FROM ins_invrepair GROUP BY service_id ORDER BY claims DESC LIMIT 10",
        "type": "top_n",
    },
    {
        "id": 187,
        "q": "What is the average repair duration in days for the top 5 busiest repair shops?",
        "sql": "WITH top5 AS (SELECT service_id FROM ins_invrepair GROUP BY service_id ORDER BY COUNT(*) DESC LIMIT 5) SELECT ir.service_id, AVG(DATEDIFF(ir.end_repair, ir.start_repair)) AS avg_days, COUNT(*) AS repairs FROM ins_invrepair ir INNER JOIN top5 t ON t.service_id=ir.service_id WHERE ir.start_repair IS NOT NULL AND ir.end_repair IS NOT NULL GROUP BY ir.service_id ORDER BY avg_days",
        "type": "distribution",
    },
    {
        "id": 188,
        "q": "What is the distribution of repair statuses?",
        "sql": "SELECT repair_status, COUNT(*) AS cnt FROM ins_invrepair GROUP BY repair_status ORDER BY cnt DESC",
        "type": "distribution",
    },
    {
        "id": 189,
        "q": "How many claims have a repair request vs how many do not?",
        "sql": "SELECT SUM(CASE WHEN ir.repair_id IS NOT NULL THEN 1 ELSE 0 END) AS with_repair, SUM(CASE WHEN ir.repair_id IS NULL THEN 1 ELSE 0 END) AS without_repair FROM ins_opis o LEFT JOIN ins_invrepair ir ON ir.opis_id=o.opis_id",
        "type": "comparison",
    },
    {
        "id": 190,
        "q": "What is the average number of days from claim filing (opis_date) to repair request (send_date)?",
        "sql": "SELECT AVG(DATEDIFF(ir.send_date, o.opis_date)) AS avg_days FROM ins_invrepair ir JOIN ins_opis o ON o.opis_id=ir.opis_id WHERE ir.send_date IS NOT NULL AND o.opis_date IS NOT NULL",
        "type": "numeric",
    },
    {
        "id": 191,
        "q": "How many repairs have a start date but no end date?",
        "sql": "SELECT COUNT(*) FROM ins_invrepair WHERE start_repair IS NOT NULL AND end_repair IS NULL",
        "type": "count",
    },
    {
        "id": 192,
        "q": "Which top 5 repair shops have the most completed repairs (repair_status=1000)?",
        "sql": "SELECT service_id, COUNT(*) AS completed FROM ins_invrepair WHERE repair_status=1000 GROUP BY service_id ORDER BY completed DESC LIMIT 5",
        "type": "top_n",
    },
    {
        "id": 193,
        "q": "What is the overall average repair duration in days (where both start and end dates exist)?",
        "sql": "SELECT AVG(DATEDIFF(end_repair, start_repair)) AS avg_days FROM ins_invrepair WHERE start_repair IS NOT NULL AND end_repair IS NOT NULL",
        "type": "numeric",
    },
    {
        "id": 194,
        "q": "How many repair claims exist per car make (car_make_name)?",
        "sql": "SELECT car_make_name, COUNT(*) AS cnt FROM ins_invrepair WHERE car_make_name IS NOT NULL AND car_make_name != '' GROUP BY car_make_name ORDER BY cnt DESC",
        "type": "distribution",
    },
    {
        "id": 195,
        "q": "What is the repair completion rate (repairs with end_repair / total repairs)?",
        "sql": "SELECT ROUND(100.0 * SUM(CASE WHEN end_repair IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 2) AS completion_rate_pct FROM ins_invrepair",
        "type": "numeric",
    },
    {
        "id": 196,
        "q": "Which repair shops have the fastest average repair time? Show top 5 with at least 5 completed repairs.",
        "sql": "SELECT service_id, AVG(DATEDIFF(end_repair, start_repair)) AS avg_days, COUNT(*) AS repairs FROM ins_invrepair WHERE start_repair IS NOT NULL AND end_repair IS NOT NULL GROUP BY service_id HAVING repairs >= 5 ORDER BY avg_days ASC LIMIT 5",
        "type": "top_n",
    },
    {
        "id": 197,
        "q": "How many repair requests were sent per year?",
        "sql": "SELECT YEAR(send_date) AS yr, COUNT(*) AS cnt FROM ins_invrepair WHERE send_date IS NOT NULL GROUP BY yr ORDER BY yr",
        "type": "distribution",
    },
    {
        "id": 198,
        "q": "How many repair requests were sent per month?",
        "sql": "SELECT DATE_FORMAT(send_date, '%Y-%m') AS month, COUNT(*) AS cnt FROM ins_invrepair WHERE send_date IS NOT NULL GROUP BY month ORDER BY month",
        "type": "distribution",
    },
    {
        "id": 199,
        "q": "Which repair shops handle the most diverse set of car brands? Show top 5 by distinct car_make_name count.",
        "sql": "SELECT service_id, COUNT(DISTINCT car_make_name) AS brand_count, COUNT(*) AS total_repairs FROM ins_invrepair WHERE car_make_name IS NOT NULL AND car_make_name != '' GROUP BY service_id ORDER BY brand_count DESC LIMIT 5",
        "type": "top_n",
    },
    {
        "id": 200,
        "q": "What is the average number of days from send_date to start_repair?",
        "sql": "SELECT AVG(DATEDIFF(start_repair, send_date)) AS avg_days FROM ins_invrepair WHERE send_date IS NOT NULL AND start_repair IS NOT NULL",
        "type": "numeric",
    },
    {
        "id": 201,
        "q": "How many claims have multiple repair records?",
        "sql": "SELECT COUNT(*) FROM (SELECT opis_id FROM ins_invrepair GROUP BY opis_id HAVING COUNT(*) > 1) t",
        "type": "count",
    },
    {
        "id": 202,
        "q": "How many repairs are still pending (repair_status=0)?",
        "sql": "SELECT COUNT(*) FROM ins_invrepair WHERE repair_status=0",
        "type": "count",
    },
    {
        "id": 203,
        "q": "What are the 5 longest repair durations (in days)?",
        "sql": "SELECT repair_id, service_id, DATEDIFF(end_repair, start_repair) AS days FROM ins_invrepair WHERE start_repair IS NOT NULL AND end_repair IS NOT NULL ORDER BY days DESC LIMIT 5",
        "type": "top_n",
    },
    {
        "id": 204,
        "q": "How many repair requests were sent per quarter?",
        "sql": "SELECT YEAR(send_date) AS yr, QUARTER(send_date) AS qtr, COUNT(*) AS cnt FROM ins_invrepair WHERE send_date IS NOT NULL GROUP BY yr, qtr ORDER BY yr, qtr",
        "type": "distribution",
    },
    {
        "id": 205,
        "q": "What is the average number of repairs per repair shop?",
        "sql": "SELECT AVG(cnt) FROM (SELECT service_id, COUNT(*) AS cnt FROM ins_invrepair GROUP BY service_id) t",
        "type": "numeric",
    },
    {
        "id": 206,
        "q": "How many claims were sent to a repair shop but are still pending (repair_status=0)?",
        "sql": "SELECT COUNT(*) FROM ins_invrepair WHERE repair_status = 0 AND send_date IS NOT NULL",
        "type": "count",
    },
    {
        "id": 207,
        "q": "Which repair shops have a 100% completion rate (all repairs have repair_status=1000)? Show shops with at least 5 repairs.",
        "sql": "SELECT service_id, COUNT(*) AS total, SUM(CASE WHEN repair_status=1000 THEN 1 ELSE 0 END) AS completed FROM ins_invrepair GROUP BY service_id HAVING total >= 5 AND completed = total ORDER BY total DESC",
        "type": "top_n",
    },
    {
        "id": 208,
        "q": "What is the distribution of repair durations in buckets (0-7 days, 8-14, 15-30, 31-60, 60+ days)?",
        "sql": "SELECT CASE WHEN d <= 7 THEN '0-7' WHEN d <= 14 THEN '8-14' WHEN d <= 30 THEN '15-30' WHEN d <= 60 THEN '31-60' ELSE '60+' END AS duration_bucket, COUNT(*) AS cnt FROM (SELECT DATEDIFF(end_repair, start_repair) AS d FROM ins_invrepair WHERE start_repair IS NOT NULL AND end_repair IS NOT NULL) t GROUP BY duration_bucket ORDER BY MIN(d)",
        "type": "distribution",
    },
    {
        "id": 209,
        "q": "Which repair shops have handled repairs across the most years? Show top 5.",
        "sql": "SELECT service_id, COUNT(DISTINCT YEAR(send_date)) AS years_active, COUNT(*) AS repairs FROM ins_invrepair WHERE send_date IS NOT NULL GROUP BY service_id ORDER BY years_active DESC, repairs DESC LIMIT 5",
        "type": "top_n",
    },
    {
        "id": 210,
        "q": "How many claims have both a repair request and an MC estimate?",
        "sql": "SELECT COUNT(DISTINCT ir.opis_id) FROM ins_invrepair ir INNER JOIN ins_mc_invcalc ic ON ic.opis_id=ir.opis_id WHERE ic.type='mc'",
        "type": "count",
    },

    # ======================================================================
    # Cat 6: MC vs N24 Comparison (Q211-Q225)
    # ======================================================================
    {
        "id": 211,
        "q": "How many claims have both MC and N24 estimates?",
        "sql": "SELECT COUNT(*) FROM (SELECT opis_id FROM ins_mc_invcalc GROUP BY opis_id HAVING COUNT(DISTINCT type) = 2) t",
        "type": "count",
    },
    {
        "id": 212,
        "q": "What is the average MC total cost vs average N24 total cost (from latest estimates)?",
        "sql": "WITH latest AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, type, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc GROUP BY opis_id, type) lt ON lt.opis_id=ic.opis_id AND lt.type=ic.type AND lt.max_id=ic.invcalc_id) SELECT AVG(CASE WHEN type='mc' THEN total_cost END) AS avg_mc, AVG(CASE WHEN type='n24' THEN total_cost END) AS avg_n24 FROM latest",
        "type": "comparison",
    },
    {
        "id": 213,
        "q": "For claims with both MC and N24, what is the average MC minus N24 cost difference?",
        "sql": "WITH latest AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, type, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc GROUP BY opis_id, type) lt ON lt.opis_id=ic.opis_id AND lt.type=ic.type AND lt.max_id=ic.invcalc_id), mc AS (SELECT opis_id, total_cost FROM latest WHERE type='mc'), n24 AS (SELECT opis_id, total_cost FROM latest WHERE type='n24') SELECT AVG(mc.total_cost - n24.total_cost) AS avg_diff FROM mc JOIN n24 ON n24.opis_id=mc.opis_id",
        "type": "numeric",
    },
    {
        "id": 214,
        "q": "How many claims have N24 estimate exceeding MC estimate?",
        "sql": "WITH latest AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, type, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc GROUP BY opis_id, type) lt ON lt.opis_id=ic.opis_id AND lt.type=ic.type AND lt.max_id=ic.invcalc_id), mc AS (SELECT opis_id, total_cost FROM latest WHERE type='mc'), n24 AS (SELECT opis_id, total_cost FROM latest WHERE type='n24') SELECT COUNT(*) FROM mc JOIN n24 ON n24.opis_id=mc.opis_id WHERE n24.total_cost > mc.total_cost",
        "type": "count",
    },
    {
        "id": 215,
        "q": "How many claims have MC estimate exceeding N24 estimate?",
        "sql": "WITH latest AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, type, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc GROUP BY opis_id, type) lt ON lt.opis_id=ic.opis_id AND lt.type=ic.type AND lt.max_id=ic.invcalc_id), mc AS (SELECT opis_id, total_cost FROM latest WHERE type='mc'), n24 AS (SELECT opis_id, total_cost FROM latest WHERE type='n24') SELECT COUNT(*) FROM mc JOIN n24 ON n24.opis_id=mc.opis_id WHERE mc.total_cost > n24.total_cost",
        "type": "count",
    },
    {
        "id": 216,
        "q": "What is the average MC/N24 cost ratio for claims that have both estimates?",
        "sql": "WITH latest AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, type, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc GROUP BY opis_id, type) lt ON lt.opis_id=ic.opis_id AND lt.type=ic.type AND lt.max_id=ic.invcalc_id), mc AS (SELECT opis_id, total_cost FROM latest WHERE type='mc'), n24 AS (SELECT opis_id, total_cost FROM latest WHERE type='n24') SELECT AVG(mc.total_cost / NULLIF(n24.total_cost, 0)) AS avg_ratio FROM mc JOIN n24 ON n24.opis_id=mc.opis_id WHERE n24.total_cost > 0",
        "type": "numeric",
    },
    {
        "id": 217,
        "q": "For claims with both estimates, how does the parts cost compare between MC and N24?",
        "sql": "WITH latest AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, type, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc GROUP BY opis_id, type) lt ON lt.opis_id=ic.opis_id AND lt.type=ic.type AND lt.max_id=ic.invcalc_id), mc AS (SELECT opis_id, newparts_cost FROM latest WHERE type='mc'), n24 AS (SELECT opis_id, newparts_cost FROM latest WHERE type='n24') SELECT AVG(mc.newparts_cost) AS avg_mc_parts, AVG(n24.newparts_cost) AS avg_n24_parts FROM mc JOIN n24 ON n24.opis_id=mc.opis_id",
        "type": "comparison",
    },
    {
        "id": 218,
        "q": "For claims with both estimates, how does the paint cost compare between MC and N24?",
        "sql": "WITH latest AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, type, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc GROUP BY opis_id, type) lt ON lt.opis_id=ic.opis_id AND lt.type=ic.type AND lt.max_id=ic.invcalc_id), mc AS (SELECT opis_id, paints_cost FROM latest WHERE type='mc'), n24 AS (SELECT opis_id, paints_cost FROM latest WHERE type='n24') SELECT AVG(mc.paints_cost) AS avg_mc_paint, AVG(n24.paints_cost) AS avg_n24_paint FROM mc JOIN n24 ON n24.opis_id=mc.opis_id",
        "type": "comparison",
    },
    {
        "id": 219,
        "q": "For claims with both estimates, how does the repair labor cost compare between MC and N24?",
        "sql": "WITH latest AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, type, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc GROUP BY opis_id, type) lt ON lt.opis_id=ic.opis_id AND lt.type=ic.type AND lt.max_id=ic.invcalc_id), mc AS (SELECT opis_id, repairs_cost FROM latest WHERE type='mc'), n24 AS (SELECT opis_id, repairs_cost FROM latest WHERE type='n24') SELECT AVG(mc.repairs_cost) AS avg_mc_repairs, AVG(n24.repairs_cost) AS avg_n24_repairs FROM mc JOIN n24 ON n24.opis_id=mc.opis_id",
        "type": "comparison",
    },
    {
        "id": 220,
        "q": "What is the MC vs N24 average cost difference by car brand? Show brands with both estimates.",
        "sql": "WITH latest AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, type, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc GROUP BY opis_id, type) lt ON lt.opis_id=ic.opis_id AND lt.type=ic.type AND lt.max_id=ic.invcalc_id), mc AS (SELECT opis_id, total_cost FROM latest WHERE type='mc'), n24 AS (SELECT opis_id, total_cost FROM latest WHERE type='n24') SELECT b.brand_name, AVG(mc.total_cost - n24.total_cost) AS avg_diff, COUNT(*) AS claims FROM mc JOIN n24 ON n24.opis_id=mc.opis_id JOIN ins_opis o ON o.opis_id=mc.opis_id JOIN ins_cars c ON c.car_id=o.car_id JOIN srv_mc_horizon_brand b ON c.car_mc_brand=b.brand_id GROUP BY b.brand_name ORDER BY avg_diff DESC",
        "type": "distribution",
    },
    {
        "id": 221,
        "q": "What is the MC vs N24 average cost difference by damage type?",
        "sql": "WITH latest AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, type, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc GROUP BY opis_id, type) lt ON lt.opis_id=ic.opis_id AND lt.type=ic.type AND lt.max_id=ic.invcalc_id), mc AS (SELECT opis_id, total_cost FROM latest WHERE type='mc'), n24 AS (SELECT opis_id, total_cost FROM latest WHERE type='n24') SELECT d.damage_typeid, AVG(mc.total_cost - n24.total_cost) AS avg_diff, COUNT(*) AS claims FROM mc JOIN n24 ON n24.opis_id=mc.opis_id JOIN ins_opis o ON o.opis_id=mc.opis_id JOIN ins_damages d ON d.damage_id=o.damage_id GROUP BY d.damage_typeid ORDER BY avg_diff DESC",
        "type": "distribution",
    },
    {
        "id": 222,
        "q": "How many N24 estimates exist in total?",
        "sql": "SELECT COUNT(*) FROM ins_mc_invcalc WHERE type='n24'",
        "type": "count",
    },
    {
        "id": 223,
        "q": "What is the average N24 estimated total cost?",
        "sql": "WITH latest_n24 AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='n24' GROUP BY opis_id) ln ON ln.opis_id=ic.opis_id AND ln.max_id=ic.invcalc_id) SELECT AVG(total_cost) AS avg_n24_cost FROM latest_n24",
        "type": "numeric",
    },
    {
        "id": 224,
        "q": "How many N24 estimates were created per year?",
        "sql": "SELECT YEAR(o.opis_date) AS yr, COUNT(*) AS cnt FROM ins_mc_invcalc ic JOIN ins_opis o ON o.opis_id=ic.opis_id WHERE ic.type='n24' AND o.opis_date IS NOT NULL GROUP BY yr ORDER BY yr",
        "type": "distribution",
    },
    {
        "id": 225,
        "q": "How many claims have only N24 estimates (no MC)?",
        "sql": "SELECT COUNT(*) FROM (SELECT opis_id FROM ins_mc_invcalc GROUP BY opis_id HAVING SUM(CASE WHEN type='n24' THEN 1 ELSE 0 END) > 0 AND SUM(CASE WHEN type='mc' THEN 1 ELSE 0 END) = 0) t",
        "type": "count",
    },

    # ======================================================================
    # Cat 7: Cycle Time & Process (Q226-Q245)
    # ======================================================================
    {
        "id": 226,
        "q": "What is the average number of days from accident (damage_date) to claim filing (opis_date)?",
        "sql": "SELECT AVG(DATEDIFF(o.opis_date, d.damage_date)) AS avg_days FROM ins_opis o JOIN ins_damages d ON d.damage_id=o.damage_id WHERE d.damage_date IS NOT NULL AND o.opis_date IS NOT NULL",
        "type": "numeric",
    },
    {
        "id": 227,
        "q": "What is the average number of days from claim filing (opis_date) to repair request (send_date)?",
        "sql": "SELECT AVG(DATEDIFF(ir.send_date, o.opis_date)) AS avg_days FROM ins_invrepair ir JOIN ins_opis o ON o.opis_id=ir.opis_id WHERE ir.send_date IS NOT NULL AND o.opis_date IS NOT NULL",
        "type": "numeric",
    },
    {
        "id": 228,
        "q": "What is the average repair duration from start to end in days?",
        "sql": "SELECT AVG(DATEDIFF(end_repair, start_repair)) AS avg_days FROM ins_invrepair WHERE start_repair IS NOT NULL AND end_repair IS NOT NULL",
        "type": "numeric",
    },
    {
        "id": 229,
        "q": "How many claims were filed on the same day as the damage event?",
        "sql": "SELECT COUNT(*) FROM ins_opis o JOIN ins_damages d ON d.damage_id=o.damage_id WHERE CAST(o.opis_date AS DATE) = d.damage_date AND d.damage_date IS NOT NULL",
        "type": "count",
    },
    {
        "id": 230,
        "q": "How many claims were filed more than 90 days after the damage event?",
        "sql": "SELECT COUNT(*) FROM ins_opis o JOIN ins_damages d ON d.damage_id=o.damage_id WHERE d.damage_date IS NOT NULL AND o.opis_date IS NOT NULL AND DATEDIFF(o.opis_date, d.damage_date) > 90",
        "type": "count",
    },
    {
        "id": 231,
        "q": "What is the average number of days from damage event to repair request being sent?",
        "sql": "SELECT AVG(DATEDIFF(ir.send_date, d.damage_date)) AS avg_days FROM ins_invrepair ir JOIN ins_opis o ON o.opis_id=ir.opis_id JOIN ins_damages d ON d.damage_id=o.damage_id WHERE d.damage_date IS NOT NULL AND ir.send_date IS NOT NULL",
        "type": "numeric",
    },
    {
        "id": 232,
        "q": "How many claims have multiple generated documents (inspections)?",
        "sql": "SELECT COUNT(*) FROM (SELECT opis_id FROM ins_gendocs GROUP BY opis_id HAVING COUNT(*) >= 2) t",
        "type": "count",
    },
    {
        "id": 233,
        "q": "What is the average number of generated documents per claim?",
        "sql": "SELECT AVG(cnt) FROM (SELECT opis_id, COUNT(*) AS cnt FROM ins_gendocs GROUP BY opis_id) t",
        "type": "numeric",
    },
    {
        "id": 234,
        "q": "What is the distribution of estimate revision counts (number of MC invcalc records) per claim?",
        "sql": "SELECT revisions, COUNT(*) AS claims FROM (SELECT opis_id, COUNT(*) AS revisions FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) t GROUP BY revisions ORDER BY revisions",
        "type": "distribution",
    },
    {
        "id": 235,
        "q": "How many claims have 3 or more MC estimate revisions?",
        "sql": "SELECT COUNT(*) FROM (SELECT opis_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id HAVING COUNT(*) >= 3) t",
        "type": "count",
    },
    {
        "id": 236,
        "q": "What is the average number of days between the damage event and the first generated document?",
        "sql": "SELECT AVG(DATEDIFF(g.first_gen, d.damage_date)) AS avg_days FROM ins_damages d JOIN ins_opis o ON o.damage_id=d.damage_id JOIN (SELECT opis_id, MIN(gen_date) AS first_gen FROM ins_gendocs GROUP BY opis_id) g ON g.opis_id=o.opis_id WHERE d.damage_date IS NOT NULL",
        "type": "numeric",
    },
    {
        "id": 237,
        "q": "What is the distribution of repair durations in days (0-7, 8-14, 15-30, 31+ days)?",
        "sql": "SELECT CASE WHEN d <= 7 THEN '0-7' WHEN d <= 14 THEN '8-14' WHEN d <= 30 THEN '15-30' ELSE '31+' END AS bucket, COUNT(*) AS cnt FROM (SELECT DATEDIFF(end_repair, start_repair) AS d FROM ins_invrepair WHERE start_repair IS NOT NULL AND end_repair IS NOT NULL) t GROUP BY bucket ORDER BY MIN(d)",
        "type": "distribution",
    },
    {
        "id": 238,
        "q": "What are the 5 fastest completed repairs (shortest duration in days)?",
        "sql": "SELECT repair_id, service_id, DATEDIFF(end_repair, start_repair) AS days FROM ins_invrepair WHERE start_repair IS NOT NULL AND end_repair IS NOT NULL AND end_repair >= start_repair ORDER BY days ASC LIMIT 5",
        "type": "top_n",
    },
    {
        "id": 239,
        "q": "How many repairs have a start_repair date before the claim filing date (opis_date)?",
        "sql": "SELECT COUNT(*) FROM ins_invrepair ir JOIN ins_opis o ON o.opis_id=ir.opis_id WHERE ir.start_repair IS NOT NULL AND o.opis_date IS NOT NULL AND ir.start_repair < CAST(o.opis_date AS DATE)",
        "type": "count",
    },
    {
        "id": 240,
        "q": "What is the average filing lag (damage_date to opis_date) by claim_type?",
        "sql": "SELECT o.claim_type, AVG(DATEDIFF(o.opis_date, d.damage_date)) AS avg_lag_days FROM ins_opis o JOIN ins_damages d ON d.damage_id=o.damage_id WHERE d.damage_date IS NOT NULL AND o.opis_date IS NOT NULL GROUP BY o.claim_type ORDER BY avg_lag_days",
        "type": "distribution",
    },
    {
        "id": 241,
        "q": "What is the monthly average filing lag trend?",
        "sql": "SELECT DATE_FORMAT(o.opis_date, '%Y-%m') AS month, AVG(DATEDIFF(o.opis_date, d.damage_date)) AS avg_lag FROM ins_opis o JOIN ins_damages d ON d.damage_id=o.damage_id WHERE d.damage_date IS NOT NULL AND o.opis_date IS NOT NULL GROUP BY month ORDER BY month",
        "type": "distribution",
    },
    {
        "id": 242,
        "q": "How many claims have generated documents but no MC estimate?",
        "sql": "SELECT COUNT(DISTINCT g.opis_id) FROM ins_gendocs g LEFT JOIN ins_mc_invcalc ic ON ic.opis_id=g.opis_id AND ic.type='mc' WHERE ic.opis_id IS NULL",
        "type": "count",
    },
    {
        "id": 243,
        "q": "What is the average number of days from repair request (send_date) to repair start?",
        "sql": "SELECT AVG(DATEDIFF(start_repair, send_date)) AS avg_days FROM ins_invrepair WHERE send_date IS NOT NULL AND start_repair IS NOT NULL",
        "type": "numeric",
    },
    {
        "id": 244,
        "q": "How many repairs were completed before the estimated_date_repair?",
        "sql": "SELECT COUNT(*) FROM ins_invrepair WHERE end_repair IS NOT NULL AND estimated_date_repair IS NOT NULL AND end_repair < estimated_date_repair",
        "type": "count",
    },
    {
        "id": 245,
        "q": "What is the average total lifecycle duration (from damage_date to end_repair) in days?",
        "sql": "SELECT AVG(DATEDIFF(ir.end_repair, d.damage_date)) AS avg_days FROM ins_invrepair ir JOIN ins_opis o ON o.opis_id=ir.opis_id JOIN ins_damages d ON d.damage_id=o.damage_id WHERE d.damage_date IS NOT NULL AND ir.end_repair IS NOT NULL",
        "type": "numeric",
    },

    # ======================================================================
    # Cat 8: Data Quality Checks (Q246-Q265)
    # ======================================================================
    {
        "id": 246,
        "q": "How many claims (opis) reference a damage_id that does not exist in ins_damages?",
        "sql": "SELECT COUNT(*) FROM ins_opis o LEFT JOIN ins_damages d ON d.damage_id=o.damage_id WHERE d.damage_id IS NULL",
        "type": "count",
    },
    {
        "id": 247,
        "q": "How many opis_rows reference an opis_id that does not exist in ins_opis?",
        "sql": "SELECT COUNT(*) FROM ins_opis_rows r LEFT JOIN ins_opis o ON o.opis_id=r.opis_id WHERE o.opis_id IS NULL",
        "type": "count",
    },
    {
        "id": 248,
        "q": "How many MC estimates reference an opis_id that does not exist in ins_opis?",
        "sql": "SELECT COUNT(*) FROM ins_mc_invcalc ic LEFT JOIN ins_opis o ON o.opis_id=ic.opis_id WHERE o.opis_id IS NULL",
        "type": "count",
    },
    {
        "id": 249,
        "q": "How many opis_rows have a part_id outside the known catalog ranges (not in SC < 10M, MC 10M-20M, or Free >= 20M)?",
        "sql": "SELECT COUNT(*) FROM ins_opis_rows WHERE part_id < 0 OR part_id >= 30000000",
        "type": "count",
    },
    {
        "id": 250,
        "q": "How many opis_rows reference a part_id that has no matching record in any parts catalog?",
        "sql": "SELECT COUNT(*) FROM ins_opis_rows r LEFT JOIN ins_partsindex pi ON r.part_id=pi.part_id AND r.part_id < 10000000 LEFT JOIN ins_partsomc po ON r.part_id=po.part_id AND r.part_id >= 10000000 AND r.part_id < 20000000 LEFT JOIN ins_partsfree pf ON r.part_id=pf.part_id AND r.part_id >= 20000000 WHERE pi.part_id IS NULL AND po.part_id IS NULL AND pf.part_id IS NULL",
        "type": "count",
    },
    {
        "id": 251,
        "q": "How many MC estimates have negative cost values (total_cost < 0 or newparts_cost < 0)?",
        "sql": "SELECT COUNT(*) FROM ins_mc_invcalc WHERE total_cost < 0 OR newparts_cost < 0 OR repairs_cost < 0 OR paints_cost < 0",
        "type": "count",
    },
    {
        "id": 252,
        "q": "How many claims were filed (opis_date) before the damage event (damage_date)?",
        "sql": "SELECT COUNT(*) FROM ins_opis o JOIN ins_damages d ON d.damage_id=o.damage_id WHERE d.damage_date IS NOT NULL AND o.opis_date IS NOT NULL AND CAST(o.opis_date AS DATE) < d.damage_date",
        "type": "count",
    },
    {
        "id": 253,
        "q": "How many repair requests (send_date) were sent before the claim was filed (opis_date)?",
        "sql": "SELECT COUNT(*) FROM ins_invrepair ir JOIN ins_opis o ON o.opis_id=ir.opis_id WHERE ir.send_date IS NOT NULL AND o.opis_date IS NOT NULL AND ir.send_date < o.opis_date",
        "type": "count",
    },
    {
        "id": 254,
        "q": "Are there any MC estimate records with type not in ('mc', 'n24')?",
        "sql": "SELECT COUNT(*) FROM ins_mc_invcalc WHERE type NOT IN ('mc', 'n24')",
        "type": "count",
    },
    {
        "id": 255,
        "q": "How many opis records reference a non-zero car_id that does not exist in ins_cars (excluding car_id=0 sentinel)?",
        "sql": "SELECT COUNT(*) FROM ins_opis o LEFT JOIN ins_cars c ON c.car_id=o.car_id WHERE o.car_id > 0 AND c.car_id IS NULL",
        "type": "count",
    },
    {
        "id": 256,
        "q": "How many opis records reference a damage_id that does not exist in ins_damages?",
        "sql": "SELECT COUNT(*) FROM ins_opis o LEFT JOIN ins_damages d ON d.damage_id=o.damage_id WHERE o.damage_id > 0 AND d.damage_id IS NULL",
        "type": "count",
    },
    {
        "id": 257,
        "q": "How many damage events have a future damage_date (after today)?",
        "sql": "SELECT COUNT(*) FROM ins_damages WHERE damage_date > CURDATE()",
        "type": "count",
    },
    {
        "id": 258,
        "q": "How many cars have an invalid manufacturing year (before 1900 or after 2026)?",
        "sql": "SELECT COUNT(*) FROM ins_cars WHERE car_year < 1900 OR car_year > 2026",
        "type": "count",
    },
    {
        "id": 259,
        "q": "How many MC estimates have total_cost that differs from the sum of component costs (parts + repairs + mounts + paints + other) by more than 1 BGN?",
        "sql": "SELECT COUNT(*) FROM ins_mc_invcalc WHERE ABS(total_cost - (newparts_cost + repairs_cost + mounts_cost + paints_cost + other_cost)) > 1 AND total_cost > 0",
        "type": "count",
    },
    {
        "id": 260,
        "q": "How many expense lines have negative values (value_vat < 0)?",
        "sql": "SELECT COUNT(*) FROM ins_mc_invexpenses WHERE value_vat < 0",
        "type": "count",
    },
    {
        "id": 261,
        "q": "Are there any duplicate opis_rows (same opis_id and part_id appearing more than once)?",
        "sql": "SELECT COUNT(*) FROM (SELECT opis_id, part_id FROM ins_opis_rows GROUP BY opis_id, part_id HAVING COUNT(*) > 1) t",
        "type": "count",
    },
    {
        "id": 262,
        "q": "How many claims have opis_date earlier than damage_date by more than 1 day?",
        "sql": "SELECT COUNT(*) FROM ins_opis o JOIN ins_damages d ON d.damage_id=o.damage_id WHERE d.damage_date IS NOT NULL AND o.opis_date IS NOT NULL AND DATEDIFF(d.damage_date, CAST(o.opis_date AS DATE)) > 1",
        "type": "count",
    },
    {
        "id": 263,
        "q": "How many repairs have end_repair before start_repair?",
        "sql": "SELECT COUNT(*) FROM ins_invrepair WHERE start_repair IS NOT NULL AND end_repair IS NOT NULL AND end_repair < start_repair",
        "type": "count",
    },
    {
        "id": 264,
        "q": "How many MC estimates are inactive (is_active=0)?",
        "sql": "SELECT COUNT(*) FROM ins_mc_invcalc WHERE is_active=0",
        "type": "count",
    },
    {
        "id": 265,
        "q": "How many expense lines reference a doc_id (invcalc_id) that does not exist in ins_mc_invcalc?",
        "sql": "SELECT COUNT(*) FROM ins_mc_invexpenses e LEFT JOIN ins_mc_invcalc ic ON ic.invcalc_id=e.doc_id WHERE ic.invcalc_id IS NULL",
        "type": "count",
    },

    # ======================================================================
    # Cat 9: Geographic & Location Analysis (Q266-Q280)
    # ======================================================================
    {
        "id": 266,
        "q": "What is the average damage total_cost by country (damage_place_country)?",
        "sql": "SELECT damage_place_country, AVG(total_cost) AS avg_cost, COUNT(*) AS claims FROM ins_damages WHERE damage_place_country IS NOT NULL AND damage_place_country != '' GROUP BY damage_place_country ORDER BY avg_cost DESC",
        "type": "distribution",
    },
    {
        "id": 267,
        "q": "What are the top 10 damage locations by frequency?",
        "sql": "SELECT damage_place, COUNT(*) AS cnt FROM ins_damages WHERE damage_place IS NOT NULL AND damage_place != '' GROUP BY damage_place ORDER BY cnt DESC LIMIT 10",
        "type": "top_n",
    },
    {
        "id": 268,
        "q": "How many claims exist per country (damage_place_country)?",
        "sql": "SELECT damage_place_country, COUNT(*) AS cnt FROM ins_damages WHERE damage_place_country IS NOT NULL AND damage_place_country != '' GROUP BY damage_place_country ORDER BY cnt DESC",
        "type": "distribution",
    },
    {
        "id": 269,
        "q": "What is the average MC estimated cost by country?",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id) SELECT d.damage_place_country, AVG(mc.total_cost) AS avg_cost, COUNT(*) AS claims FROM latest_mc mc JOIN ins_opis o ON o.opis_id=mc.opis_id JOIN ins_damages d ON d.damage_id=o.damage_id WHERE d.damage_place_country IS NOT NULL AND d.damage_place_country != '' GROUP BY d.damage_place_country ORDER BY avg_cost DESC",
        "type": "distribution",
    },
    {
        "id": 270,
        "q": "How many claims occurred in Sofia vs all other locations?",
        "sql": "SELECT CASE WHEN damage_place LIKE '%София%' THEN 'Sofia' ELSE 'Other' END AS location_group, COUNT(*) AS cnt FROM ins_damages WHERE damage_place IS NOT NULL AND damage_place != '' GROUP BY location_group",
        "type": "comparison",
    },
    {
        "id": 271,
        "q": "What is the damage type distribution by country?",
        "sql": "SELECT d.damage_place_country, d.damage_typeid, COUNT(*) AS cnt FROM ins_damages d WHERE d.damage_place_country IS NOT NULL AND d.damage_place_country != '' GROUP BY d.damage_place_country, d.damage_typeid ORDER BY d.damage_place_country, cnt DESC",
        "type": "distribution",
    },
    {
        "id": 272,
        "q": "What is the average filing lag by country?",
        "sql": "SELECT d.damage_place_country, AVG(DATEDIFF(o.opis_date, d.damage_date)) AS avg_lag FROM ins_opis o JOIN ins_damages d ON d.damage_id=o.damage_id WHERE d.damage_place_country IS NOT NULL AND d.damage_place_country != '' AND d.damage_date IS NOT NULL AND o.opis_date IS NOT NULL GROUP BY d.damage_place_country ORDER BY avg_lag",
        "type": "distribution",
    },
    {
        "id": 273,
        "q": "What are the top 10 damage locations by total cost?",
        "sql": "SELECT damage_place, SUM(total_cost) AS total, COUNT(*) AS claims FROM ins_damages WHERE damage_place IS NOT NULL AND damage_place != '' GROUP BY damage_place ORDER BY total DESC LIMIT 10",
        "type": "top_n",
    },
    {
        "id": 274,
        "q": "What is the average repair duration by damage location? Show top 5 locations with most repairs.",
        "sql": "SELECT d.damage_place, AVG(DATEDIFF(ir.end_repair, ir.start_repair)) AS avg_days, COUNT(*) AS repairs FROM ins_invrepair ir JOIN ins_opis o ON o.opis_id=ir.opis_id JOIN ins_damages d ON d.damage_id=o.damage_id WHERE d.damage_place IS NOT NULL AND d.damage_place != '' AND ir.start_repair IS NOT NULL AND ir.end_repair IS NOT NULL GROUP BY d.damage_place HAVING repairs >= 3 ORDER BY repairs DESC LIMIT 5",
        "type": "top_n",
    },
    {
        "id": 275,
        "q": "How many claims have no damage place information (empty or null)?",
        "sql": "SELECT COUNT(*) FROM ins_damages WHERE damage_place IS NULL OR damage_place = ''",
        "type": "count",
    },
    {
        "id": 276,
        "q": "How many distinct damage locations exist in the database?",
        "sql": "SELECT COUNT(DISTINCT damage_place) FROM ins_damages WHERE damage_place IS NOT NULL AND damage_place != ''",
        "type": "count",
    },
    {
        "id": 277,
        "q": "Which damage location has the highest average MC estimated cost? Show top 5 with at least 3 claims.",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id) SELECT d.damage_place, AVG(mc.total_cost) AS avg_cost, COUNT(*) AS claims FROM latest_mc mc JOIN ins_opis o ON o.opis_id=mc.opis_id JOIN ins_damages d ON d.damage_id=o.damage_id WHERE d.damage_place IS NOT NULL AND d.damage_place != '' GROUP BY d.damage_place HAVING claims >= 3 ORDER BY avg_cost DESC LIMIT 5",
        "type": "top_n",
    },
    {
        "id": 278,
        "q": "What is the geographic distribution of car makes? Show top 5 brands by number of claims in Sofia.",
        "sql": "SELECT b.brand_name, COUNT(*) AS claims FROM ins_opis o JOIN ins_damages d ON d.damage_id=o.damage_id JOIN ins_cars c ON c.car_id=o.car_id JOIN srv_mc_horizon_brand b ON c.car_mc_brand=b.brand_id WHERE d.damage_place LIKE '%София%' GROUP BY b.brand_name ORDER BY claims DESC LIMIT 5",
        "type": "top_n",
    },
    {
        "id": 279,
        "q": "How many claims by country were there per year?",
        "sql": "SELECT YEAR(d.damage_date) AS yr, d.damage_place_country, COUNT(*) AS cnt FROM ins_damages d WHERE d.damage_place_country IS NOT NULL AND d.damage_place_country != '' AND d.damage_date IS NOT NULL GROUP BY yr, d.damage_place_country ORDER BY yr, cnt DESC",
        "type": "distribution",
    },
    {
        "id": 280,
        "q": "For damage locations with at least 5 claims, what is the average claim count per location?",
        "sql": "SELECT AVG(cnt) FROM (SELECT damage_place, COUNT(*) AS cnt FROM ins_damages WHERE damage_place IS NOT NULL AND damage_place != '' GROUP BY damage_place HAVING cnt >= 5) t",
        "type": "numeric",
    },

    # ======================================================================
    # Cat 10: Complex Multi-Table & Actuarial (Q281-Q300)
    # ======================================================================
    {
        "id": 281,
        "q": "How many claims have an MC estimate above the P90 threshold?",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id), p90 AS (SELECT total_cost AS threshold FROM (SELECT total_cost, ROW_NUMBER() OVER (ORDER BY total_cost) AS rn, COUNT(*) OVER() AS cnt FROM latest_mc WHERE total_cost > 0) t WHERE rn = CEIL(0.9 * cnt) LIMIT 1) SELECT COUNT(*) FROM latest_mc, p90 WHERE latest_mc.total_cost >= p90.threshold",
        "type": "count",
    },
    {
        "id": 282,
        "q": "How many claims are missing MC estimates entirely?",
        "sql": "SELECT COUNT(*) FROM ins_opis o LEFT JOIN ins_mc_invcalc ic ON ic.opis_id=o.opis_id AND ic.type='mc' WHERE ic.opis_id IS NULL",
        "type": "count",
    },
    {
        "id": 283,
        "q": "Build a claim-level summary: show brand, damage_typeid, damage_lines, and MC total_cost for claims with estimates. Show top 10 by cost.",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id), dmg_lines AS (SELECT opis_id, COUNT(*) AS damage_lines FROM ins_opis_rows GROUP BY opis_id) SELECT b.brand_name, d.damage_typeid, l.damage_lines, mc.total_cost FROM latest_mc mc JOIN ins_opis o ON o.opis_id=mc.opis_id JOIN ins_damages d ON d.damage_id=o.damage_id JOIN ins_cars c ON c.car_id=o.car_id JOIN srv_mc_horizon_brand b ON c.car_mc_brand=b.brand_id LEFT JOIN dmg_lines l ON l.opis_id=mc.opis_id ORDER BY mc.total_cost DESC LIMIT 10",
        "type": "top_n",
    },
    {
        "id": 284,
        "q": "How does vehicle age (year of damage minus car_year) affect average MC estimated cost?",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id) SELECT (YEAR(d.damage_date) - c.car_year) AS vehicle_age, AVG(mc.total_cost) AS avg_cost, COUNT(*) AS claims FROM latest_mc mc JOIN ins_opis o ON o.opis_id=mc.opis_id JOIN ins_damages d ON d.damage_id=o.damage_id JOIN ins_cars c ON c.car_id=o.car_id WHERE d.damage_date IS NOT NULL AND c.car_year > 0 AND YEAR(d.damage_date) >= c.car_year GROUP BY vehicle_age HAVING claims >= 3 ORDER BY vehicle_age",
        "type": "distribution",
    },
    {
        "id": 285,
        "q": "Show frequency-severity decomposition by brand: claim count and average MC estimated cost per brand.",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id) SELECT b.brand_name, COUNT(*) AS claims, AVG(mc.total_cost) AS avg_cost FROM latest_mc mc JOIN ins_opis o ON o.opis_id=mc.opis_id JOIN ins_cars c ON c.car_id=o.car_id JOIN srv_mc_horizon_brand b ON c.car_mc_brand=b.brand_id GROUP BY b.brand_name ORDER BY claims DESC",
        "type": "distribution",
    },
    {
        "id": 286,
        "q": "Show claim count by claim_type and whether an MC estimate exists.",
        "sql": "SELECT o.claim_type, CASE WHEN ic.opis_id IS NOT NULL THEN 'Has MC' ELSE 'No MC' END AS mc_status, COUNT(*) AS claims FROM ins_opis o LEFT JOIN (SELECT DISTINCT opis_id FROM ins_mc_invcalc WHERE type='mc') ic ON ic.opis_id=o.opis_id GROUP BY o.claim_type, mc_status ORDER BY o.claim_type, mc_status",
        "type": "distribution",
    },
    {
        "id": 287,
        "q": "What is the average MC estimated cost for claims with major repairs (part_repair=3) vs claims without major repairs?",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id), major AS (SELECT DISTINCT opis_id FROM ins_opis_rows WHERE part_repair=3) SELECT CASE WHEN m.opis_id IS NOT NULL THEN 'Has Major' ELSE 'No Major' END AS severity, AVG(mc.total_cost) AS avg_cost, COUNT(*) AS claims FROM latest_mc mc LEFT JOIN major m ON m.opis_id=mc.opis_id GROUP BY severity",
        "type": "comparison",
    },
    {
        "id": 288,
        "q": "What is the parts share vs paint share by brand from MC estimates?",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id) SELECT b.brand_name, ROUND(100*AVG(mc.newparts_cost/NULLIF(mc.total_cost,0)),1) AS parts_share_pct, ROUND(100*AVG(mc.paints_cost/NULLIF(mc.total_cost,0)),1) AS paint_share_pct, COUNT(*) AS claims FROM latest_mc mc JOIN ins_opis o ON o.opis_id=mc.opis_id JOIN ins_cars c ON c.car_id=o.car_id JOIN srv_mc_horizon_brand b ON c.car_mc_brand=b.brand_id WHERE mc.total_cost > 0 GROUP BY b.brand_name ORDER BY parts_share_pct DESC",
        "type": "distribution",
    },
    {
        "id": 289,
        "q": "Which claims have unusually high labor hours per damage line? Show top 10.",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id), dmg_lines AS (SELECT opis_id, COUNT(*) AS damage_lines FROM ins_opis_rows GROUP BY opis_id) SELECT mc.opis_id, l.damage_lines, (mc.repairs_hours + mc.mounts_hours + mc.paints_hours) AS total_hours, ROUND((mc.repairs_hours + mc.mounts_hours + mc.paints_hours) / NULLIF(l.damage_lines, 0), 2) AS hours_per_line FROM latest_mc mc JOIN dmg_lines l ON l.opis_id=mc.opis_id WHERE l.damage_lines >= 1 ORDER BY hours_per_line DESC LIMIT 10",
        "type": "top_n",
    },
    {
        "id": 290,
        "q": "What is the claim count cross-tabulation by brand and damage_typeid? Show for top 5 brands.",
        "sql": "WITH top5 AS (SELECT b.brand_name FROM ins_opis o JOIN ins_cars c ON c.car_id=o.car_id JOIN srv_mc_horizon_brand b ON c.car_mc_brand=b.brand_id GROUP BY b.brand_name ORDER BY COUNT(*) DESC LIMIT 5) SELECT b.brand_name, d.damage_typeid, COUNT(*) AS claims FROM ins_opis o JOIN ins_damages d ON d.damage_id=o.damage_id JOIN ins_cars c ON c.car_id=o.car_id JOIN srv_mc_horizon_brand b ON c.car_mc_brand=b.brand_id INNER JOIN top5 t ON t.brand_name=b.brand_name GROUP BY b.brand_name, d.damage_typeid ORDER BY b.brand_name, d.damage_typeid",
        "type": "distribution",
    },
    {
        "id": 291,
        "q": "What is the ratio of MC estimated cost to damage total_cost? Show the average ratio.",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id) SELECT AVG(mc.total_cost / NULLIF(d.total_cost, 0)) AS avg_ratio FROM latest_mc mc JOIN ins_opis o ON o.opis_id=mc.opis_id JOIN ins_damages d ON d.damage_id=o.damage_id WHERE d.total_cost > 0",
        "type": "numeric",
    },
    {
        "id": 292,
        "q": "What are the top 5 car models (car_mc_modelname resolved via horizon) by claim frequency?",
        "sql": "SELECT mn.modelname_name, COUNT(*) AS claims FROM ins_opis o JOIN ins_cars c ON c.car_id=o.car_id JOIN srv_mc_horizon_modelname mn ON c.car_mc_modelname=mn.modelname_id GROUP BY mn.modelname_name ORDER BY claims DESC LIMIT 5",
        "type": "top_n",
    },
    {
        "id": 293,
        "q": "What is the average MC estimated cost by repair severity (based on the maximum part_repair value in the claim)?",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id), max_sev AS (SELECT opis_id, MAX(part_repair) AS max_severity FROM ins_opis_rows GROUP BY opis_id) SELECT ms.max_severity, AVG(mc.total_cost) AS avg_cost, COUNT(*) AS claims FROM latest_mc mc JOIN max_sev ms ON ms.opis_id=mc.opis_id GROUP BY ms.max_severity ORDER BY ms.max_severity",
        "type": "distribution",
    },
    {
        "id": 294,
        "q": "How many claims have both generated documents (inspections) and MC estimates?",
        "sql": "SELECT COUNT(DISTINCT o.opis_id) FROM ins_opis o INNER JOIN ins_gendocs g ON g.opis_id=o.opis_id INNER JOIN ins_mc_invcalc ic ON ic.opis_id=o.opis_id WHERE ic.type='mc'",
        "type": "count",
    },
    {
        "id": 295,
        "q": "What is the average number of damage lines by car year group?",
        "sql": "SELECT d.car_yeargroup, AVG(l.damage_lines) AS avg_lines FROM ins_opis o JOIN ins_damages d ON d.damage_id=o.damage_id JOIN (SELECT opis_id, COUNT(*) AS damage_lines FROM ins_opis_rows GROUP BY opis_id) l ON l.opis_id=o.opis_id GROUP BY d.car_yeargroup ORDER BY d.car_yeargroup",
        "type": "distribution",
    },
    {
        "id": 296,
        "q": "What is the MC estimated cost per damage line by brand?",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id), dmg_lines AS (SELECT opis_id, COUNT(*) AS damage_lines FROM ins_opis_rows GROUP BY opis_id) SELECT b.brand_name, AVG(mc.total_cost / NULLIF(l.damage_lines, 0)) AS avg_cost_per_line, COUNT(*) AS claims FROM latest_mc mc JOIN ins_opis o ON o.opis_id=mc.opis_id JOIN ins_cars c ON c.car_id=o.car_id JOIN srv_mc_horizon_brand b ON c.car_mc_brand=b.brand_id JOIN dmg_lines l ON l.opis_id=mc.opis_id GROUP BY b.brand_name ORDER BY avg_cost_per_line DESC",
        "type": "distribution",
    },
    {
        "id": 297,
        "q": "For claims with both repairs and MC estimates, what is the average MC cost vs damage total cost?",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id) SELECT AVG(mc.total_cost) AS avg_mc_cost, AVG(d.total_cost) AS avg_damage_cost, COUNT(*) AS claims FROM latest_mc mc JOIN ins_opis o ON o.opis_id=mc.opis_id JOIN ins_damages d ON d.damage_id=o.damage_id INNER JOIN ins_invrepair ir ON ir.opis_id=mc.opis_id",
        "type": "comparison",
    },
    {
        "id": 298,
        "q": "What is the supplier diversity (distinct supplier count) per brand?",
        "sql": "SELECT b.brand_name, COUNT(DISTINCT e.supplier_name) AS supplier_count, COUNT(*) AS expense_lines FROM ins_mc_invexpenses e JOIN ins_mc_invcalc ic ON e.doc_id=ic.invcalc_id JOIN ins_opis o ON o.opis_id=ic.opis_id JOIN ins_cars c ON c.car_id=o.car_id JOIN srv_mc_horizon_brand b ON c.car_mc_brand=b.brand_id WHERE e.supplier_name IS NOT NULL AND e.supplier_name != '' GROUP BY b.brand_name ORDER BY supplier_count DESC",
        "type": "distribution",
    },
    {
        "id": 299,
        "q": "What is the average MC estimated cost by filing lag bucket (0-7 days, 8-30, 31-90, 90+ days)?",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id) SELECT CASE WHEN DATEDIFF(o.opis_date, d.damage_date) <= 7 THEN '0-7 days' WHEN DATEDIFF(o.opis_date, d.damage_date) <= 30 THEN '8-30 days' WHEN DATEDIFF(o.opis_date, d.damage_date) <= 90 THEN '31-90 days' ELSE '90+ days' END AS lag_bucket, AVG(mc.total_cost) AS avg_cost, COUNT(*) AS claims FROM latest_mc mc JOIN ins_opis o ON o.opis_id=mc.opis_id JOIN ins_damages d ON d.damage_id=o.damage_id WHERE d.damage_date IS NOT NULL AND o.opis_date IS NOT NULL GROUP BY lag_bucket ORDER BY MIN(DATEDIFF(o.opis_date, d.damage_date))",
        "type": "distribution",
    },
    {
        "id": 300,
        "q": "Build a brand-level summary: brand name, total claims, average MC cost, average damage lines, and average repair duration. Show all brands with at least 5 claims.",
        "sql": "WITH latest_mc AS (SELECT ic.* FROM ins_mc_invcalc ic INNER JOIN (SELECT opis_id, MAX(invcalc_id) AS max_id FROM ins_mc_invcalc WHERE type='mc' GROUP BY opis_id) lm ON lm.opis_id=ic.opis_id AND lm.max_id=ic.invcalc_id), dmg_lines AS (SELECT opis_id, COUNT(*) AS damage_lines FROM ins_opis_rows GROUP BY opis_id), repairs AS (SELECT opis_id, AVG(DATEDIFF(end_repair, start_repair)) AS avg_repair_days FROM ins_invrepair WHERE start_repair IS NOT NULL AND end_repair IS NOT NULL GROUP BY opis_id) SELECT b.brand_name, COUNT(*) AS claims, AVG(mc.total_cost) AS avg_mc_cost, AVG(l.damage_lines) AS avg_lines, AVG(rep.avg_repair_days) AS avg_repair_days FROM latest_mc mc JOIN ins_opis o ON o.opis_id=mc.opis_id JOIN ins_cars c ON c.car_id=o.car_id JOIN srv_mc_horizon_brand b ON c.car_mc_brand=b.brand_id LEFT JOIN dmg_lines l ON l.opis_id=mc.opis_id LEFT JOIN repairs rep ON rep.opis_id=mc.opis_id GROUP BY b.brand_name HAVING claims >= 5 ORDER BY claims DESC",
        "type": "distribution",
    },
]

# Category mapping for Q101-Q300
CATEGORY_MAP_200 = {
    **{i: "Frequency" for i in range(101, 121)},
    **{i: "Cost" for i in range(121, 146)},
    **{i: "Parts" for i in range(146, 166)},
    **{i: "Supplier" for i in range(166, 186)},
    **{i: "Repair" for i in range(186, 211)},
    **{i: "MC_vs_N24" for i in range(211, 226)},
    **{i: "CycleTime" for i in range(226, 246)},
    **{i: "DataQuality" for i in range(246, 266)},
    **{i: "Geographic" for i in range(266, 281)},
    **{i: "Complex" for i in range(281, 301)},
}
