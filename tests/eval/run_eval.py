"""Evaluation harness — run questions through the agent and compare to ground truth SQL."""

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
from mcpdb.experience.cache import ExperienceCache
from mcpdb.experience.store import ExperienceStore
from mcpdb.llm.factory import create_provider
from mcpdb.sources.database.source import DatabaseSource
from mcpdb.sources.registry import SourceRegistry

# Shared experience cache — persists to ~/.mcpdb/experience/
# so eval runs warm up the cache for future production use.
_experience_store = ExperienceStore()
_experience_cache = ExperienceCache(store=_experience_store)

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("eval")

# --- Questions with ground truth SQL ---

QUESTIONS = [
    # === Category 1: Simple counts (1-10) ===
    {
        "id": 1,
        "q": "How many tables are in the database?",
        "sql": "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA='bgins'",
        "type": "count",
        "expected_value": 21,
    },
    {
        "id": 2,
        "q": "How many cars are in the ins_cars table?",
        "sql": "SELECT COUNT(*) FROM ins_cars",
        "type": "count",
    },
    {
        "id": 3,
        "q": "How many damage claims exist?",
        "sql": "SELECT COUNT(*) FROM ins_damages",
        "type": "count",
    },
    {
        "id": 4,
        "q": "How many repair records are there?",
        "sql": "SELECT COUNT(*) FROM ins_invrepair",
        "type": "count",
    },
    {
        "id": 5,
        "q": "How many parts are in the parts index?",
        "sql": "SELECT COUNT(*) FROM ins_partsindex",
        "type": "count",
    },
    {
        "id": 6,
        "q": "How many car makes are in the catalog?",
        "sql": "SELECT COUNT(*) FROM srv_mc_catalog_make WHERE mc_make_deleted = 0",
        "type": "count",
    },
    {
        "id": 7,
        "q": "How many car models exist in the catalog?",
        "sql": "SELECT COUNT(*) FROM srv_mc_catalog_model",
        "type": "count",
    },
    {
        "id": 8,
        "q": "How many expense types are defined?",
        "sql": "SELECT COUNT(*) FROM inv_exptypes",
        "type": "count",
    },
    {
        "id": 9,
        "q": "How many unique damage places are there?",
        "sql": "SELECT COUNT(DISTINCT damage_place) FROM ins_damages WHERE damage_place IS NOT NULL AND damage_place != ''",
        "type": "count",
    },
    {
        "id": 10,
        "q": "How many assessments (opis) exist?",
        "sql": "SELECT COUNT(*) FROM ins_opis",
        "type": "count",
    },

    # === Category 2: Aggregation (11-25) ===
    {
        "id": 11,
        "q": "What is the total cost of all damage claims?",
        "sql": "SELECT SUM(total_cost) FROM ins_damages",
        "type": "numeric",
    },
    {
        "id": 12,
        "q": "What is the average total cost per damage claim?",
        "sql": "SELECT AVG(total_cost) FROM ins_damages",
        "type": "numeric",
    },
    {
        "id": 13,
        "q": "What is the maximum total cost of a single damage claim?",
        "sql": "SELECT MAX(total_cost) FROM ins_damages",
        "type": "numeric",
    },
    {
        "id": 14,
        "q": "What is the minimum non-zero total cost of a damage claim?",
        "sql": "SELECT MIN(total_cost) FROM ins_damages WHERE total_cost > 0",
        "type": "numeric",
    },
    {
        "id": 15,
        "q": "What is the total compensation paid across all damages?",
        "sql": "SELECT SUM(compensation) FROM ins_damages",
        "type": "numeric",
    },
    {
        "id": 16,
        "q": "What is the average premium (premium_main) across all damages?",
        "sql": "SELECT AVG(premium_main) FROM ins_damages",
        "type": "numeric",
    },
    {
        "id": 17,
        "q": "What is the total newparts_cost across all damages?",
        "sql": "SELECT SUM(newparts_cost) FROM ins_damages",
        "type": "numeric",
    },
    {
        "id": 18,
        "q": "What is the total painting cost (paints_cost) across all damages?",
        "sql": "SELECT SUM(paints_cost) FROM ins_damages",
        "type": "numeric",
    },
    {
        "id": 19,
        "q": "What is the average repair cost per damage?",
        "sql": "SELECT AVG(repairs_cost) FROM ins_damages",
        "type": "numeric",
    },
    {
        "id": 20,
        "q": "How many damage claims have a total cost above 5000?",
        "sql": "SELECT COUNT(*) FROM ins_damages WHERE total_cost > 5000",
        "type": "count",
    },
    {
        "id": 21,
        "q": "What is the sum of transport costs across all damages?",
        "sql": "SELECT SUM(transport_cost) FROM ins_damages",
        "type": "numeric",
    },
    {
        "id": 22,
        "q": "What is the average number of items per assessment (opis)?",
        "sql": "SELECT AVG(items_count_current) FROM ins_opis",
        "type": "numeric",
    },
    {
        "id": 23,
        "q": "What is the maximum expected_value in the damages table?",
        "sql": "SELECT MAX(expected_value) FROM ins_damages",
        "type": "numeric",
    },
    {
        "id": 24,
        "q": "How many damage claims have compensation greater than zero?",
        "sql": "SELECT COUNT(*) FROM ins_damages WHERE compensation > 0",
        "type": "count",
    },
    {
        "id": 25,
        "q": "What is the total invoice calculation cost (from ins_mc_invcalc where is_active=1)?",
        "sql": "SELECT SUM(total_cost) FROM ins_mc_invcalc WHERE is_active = 1",
        "type": "numeric",
    },

    # === Category 3: Filtering and conditions (26-40) ===
    {
        "id": 26,
        "q": "How many cars were manufactured in 2020?",
        "sql": "SELECT COUNT(*) FROM ins_cars WHERE car_year = 2020",
        "type": "count",
    },
    {
        "id": 27,
        "q": "How many cars use diesel fuel (car_fuel=1)?",
        "sql": "SELECT COUNT(*) FROM ins_cars WHERE car_fuel = 1",
        "type": "count",
    },
    {
        "id": 28,
        "q": "How many damage claims are marked as regress (damage_isregress=1)?",
        "sql": "SELECT COUNT(*) FROM ins_damages WHERE damage_isregress = 1",
        "type": "count",
    },
    {
        "id": 29,
        "q": "How many repairs have status 1000 (completed)?",
        "sql": "SELECT COUNT(*) FROM ins_invrepair WHERE repair_status = 1000",
        "type": "count",
    },
    {
        "id": 30,
        "q": "How many assessments have status 1000?",
        "sql": "SELECT COUNT(*) FROM ins_opis WHERE opis_status = 1000",
        "type": "count",
    },
    {
        "id": 31,
        "q": "How many cars have car_class = 3?",
        "sql": "SELECT COUNT(*) FROM ins_cars WHERE car_class = 3",
        "type": "count",
    },
    {
        "id": 32,
        "q": "How many damage claims happened in Sofia (damage_place contains 'София')?",
        "sql": "SELECT COUNT(*) FROM ins_damages WHERE damage_place LIKE '%София%'",
        "type": "count",
    },
    {
        "id": 33,
        "q": "How many supported car makes are in the catalog (mc_supported=1)?",
        "sql": "SELECT COUNT(*) FROM srv_mc_catalog_make WHERE mc_supported = 1",
        "type": "count",
    },
    {
        "id": 34,
        "q": "How many cars have a non-empty chassis number?",
        "sql": "SELECT COUNT(*) FROM ins_cars WHERE car_chassis IS NOT NULL AND car_chassis != ''",
        "type": "count",
    },
    {
        "id": 35,
        "q": "How many damage claims occurred in 2023?",
        "sql": "SELECT COUNT(*) FROM ins_damages WHERE YEAR(damage_date) = 2023",
        "type": "count",
    },
    {
        "id": 36,
        "q": "How many generated documents have file_deleted = 0?",
        "sql": "SELECT COUNT(*) FROM ins_gendocs WHERE file_deleted = 0",
        "type": "count",
    },
    {
        "id": 37,
        "q": "How many invoice calculations are of type 'mc'?",
        "sql": "SELECT COUNT(*) FROM ins_mc_invcalc WHERE type = 'mc'",
        "type": "count",
    },
    {
        "id": 38,
        "q": "How many opis rows have part_new = 1 (new parts)?",
        "sql": "SELECT COUNT(*) FROM ins_opis_rows WHERE part_new = 1",
        "type": "count",
    },
    {
        "id": 39,
        "q": "How many damages have total_cost equal to zero?",
        "sql": "SELECT COUNT(*) FROM ins_damages WHERE total_cost = 0",
        "type": "count",
    },
    {
        "id": 40,
        "q": "How many cars are of type 1?",
        "sql": "SELECT COUNT(*) FROM ins_cars WHERE car_type = 1",
        "type": "count",
    },

    # === Category 4: Top-N and ranking (41-55) ===
    {
        "id": 41,
        "q": "What are the top 5 most expensive damage claims by total_cost?",
        "sql": "SELECT damage_id, damage_number, total_cost FROM ins_damages ORDER BY total_cost DESC LIMIT 5",
        "type": "top_n",
    },
    {
        "id": 42,
        "q": "What are the 3 most common damage places?",
        "sql": "SELECT damage_place, COUNT(*) as cnt FROM ins_damages WHERE damage_place IS NOT NULL AND damage_place != '' GROUP BY damage_place ORDER BY cnt DESC LIMIT 3",
        "type": "top_n",
    },
    {
        "id": 43,
        "q": "Which car year has the most vehicles?",
        "sql": "SELECT car_year, COUNT(*) as cnt FROM ins_cars GROUP BY car_year ORDER BY cnt DESC LIMIT 1",
        "type": "top_n",
    },
    {
        "id": 44,
        "q": "Which 5 car makes appear most often in repairs?",
        "sql": "SELECT car_make_name, COUNT(*) as cnt FROM ins_invrepair GROUP BY car_make_name ORDER BY cnt DESC LIMIT 5",
        "type": "top_n",
    },
    {
        "id": 45,
        "q": "What are the top 5 most frequently damaged parts (by part_id in opis_rows)?",
        "sql": "SELECT p.part_name, COUNT(*) as cnt FROM ins_opis_rows r JOIN ins_partsindex p ON r.part_id = p.part_id GROUP BY p.part_name ORDER BY cnt DESC LIMIT 5",
        "type": "top_n",
    },
    {
        "id": 46,
        "q": "Which damage had the highest premium_main?",
        "sql": "SELECT damage_id, damage_number, premium_main FROM ins_damages ORDER BY premium_main DESC LIMIT 1",
        "type": "top_n",
    },
    {
        "id": 47,
        "q": "What are the 5 most expensive invoice calculations (active only)?",
        "sql": "SELECT invcalc_id, opis_id, total_cost FROM ins_mc_invcalc WHERE is_active = 1 ORDER BY total_cost DESC LIMIT 5",
        "type": "top_n",
    },
    {
        "id": 48,
        "q": "Which service_id has the most repairs?",
        "sql": "SELECT service_id, COUNT(*) as cnt FROM ins_invrepair GROUP BY service_id ORDER BY cnt DESC LIMIT 1",
        "type": "top_n",
    },
    {
        "id": 49,
        "q": "Which year had the most damage claims?",
        "sql": "SELECT YEAR(damage_date) as yr, COUNT(*) as cnt FROM ins_damages WHERE damage_date IS NOT NULL GROUP BY yr ORDER BY cnt DESC LIMIT 1",
        "type": "top_n",
    },
    {
        "id": 50,
        "q": "What is the most common car_class in the cars table?",
        "sql": "SELECT car_class, COUNT(*) as cnt FROM ins_cars GROUP BY car_class ORDER BY cnt DESC LIMIT 1",
        "type": "top_n",
    },
    {
        "id": 51,
        "q": "Top 3 car makes by number of insured vehicles?",
        "sql": "SELECT m.mc_make_name, COUNT(*) as cnt FROM ins_cars c JOIN srv_mc_catalog_make m ON c.car_make = m.mc_make WHERE c.car_make > 0 GROUP BY m.mc_make_name ORDER BY cnt DESC LIMIT 3",
        "type": "top_n",
    },
    {
        "id": 52,
        "q": "Which 5 expense names are the most frequent in inv_expenses?",
        "sql": "SELECT expense_name, COUNT(*) as cnt FROM ins_mc_invexpenses GROUP BY expense_name ORDER BY cnt DESC LIMIT 5",
        "type": "top_n",
    },
    {
        "id": 53,
        "q": "Which damage place has the highest average total cost?",
        "sql": "SELECT damage_place, AVG(total_cost) as avg_cost FROM ins_damages WHERE damage_place IS NOT NULL AND damage_place != '' GROUP BY damage_place HAVING COUNT(*) >= 5 ORDER BY avg_cost DESC LIMIT 1",
        "type": "top_n",
    },
    {
        "id": 54,
        "q": "Which opis has the most rows (damaged parts)?",
        "sql": "SELECT opis_id, COUNT(*) as cnt FROM ins_opis_rows GROUP BY opis_id ORDER BY cnt DESC LIMIT 1",
        "type": "top_n",
    },
    {
        "id": 55,
        "q": "What is the longest repair duration (end_repair - start_repair) in days?",
        "sql": "SELECT repair_id, DATEDIFF(end_repair, start_repair) as days FROM ins_invrepair WHERE start_repair IS NOT NULL AND end_repair IS NOT NULL ORDER BY days DESC LIMIT 1",
        "type": "top_n",
    },

    # === Category 5: Date/time analysis (56-65) ===
    {
        "id": 56,
        "q": "What is the earliest damage date in the database?",
        "sql": "SELECT MIN(damage_date) FROM ins_damages WHERE damage_date IS NOT NULL",
        "type": "value",
    },
    {
        "id": 57,
        "q": "What is the latest damage date in the database?",
        "sql": "SELECT MAX(damage_date) FROM ins_damages WHERE damage_date IS NOT NULL",
        "type": "value",
    },
    {
        "id": 58,
        "q": "How many damages occurred per year? List all years.",
        "sql": "SELECT YEAR(damage_date) as yr, COUNT(*) as cnt FROM ins_damages WHERE damage_date IS NOT NULL GROUP BY yr ORDER BY yr",
        "type": "distribution",
    },
    {
        "id": 59,
        "q": "What is the average time between damage_date and damage_notice in days?",
        "sql": "SELECT AVG(DATEDIFF(damage_notice, damage_date)) FROM ins_damages WHERE damage_date IS NOT NULL AND damage_notice IS NOT NULL",
        "type": "numeric",
    },
    {
        "id": 60,
        "q": "How many damage claims were filed in each month of 2022?",
        "sql": "SELECT MONTH(damage_date) as m, COUNT(*) as cnt FROM ins_damages WHERE YEAR(damage_date) = 2022 GROUP BY m ORDER BY m",
        "type": "distribution",
    },
    {
        "id": 61,
        "q": "What is the earliest car registration year?",
        "sql": "SELECT MIN(YEAR(car_firstreg)) FROM ins_cars WHERE car_firstreg IS NOT NULL",
        "type": "value",
    },
    {
        "id": 62,
        "q": "What is the average age of cars at the time of damage?",
        "sql": "SELECT AVG(YEAR(d.damage_date) - c.car_year) FROM ins_opis o JOIN ins_damages d ON o.damage_id = d.damage_id JOIN ins_cars c ON o.car_id = c.car_id WHERE d.damage_date IS NOT NULL AND c.car_year > 0 AND YEAR(d.damage_date) >= c.car_year",
        "type": "numeric",
    },
    {
        "id": 63,
        "q": "Which month has the most damage claims overall?",
        "sql": "SELECT MONTH(damage_date) as m, COUNT(*) as cnt FROM ins_damages WHERE damage_date IS NOT NULL GROUP BY m ORDER BY cnt DESC LIMIT 1",
        "type": "top_n",
    },
    {
        "id": 64,
        "q": "How many repairs were completed (end_repair IS NOT NULL) per year?",
        "sql": "SELECT YEAR(end_repair) as yr, COUNT(*) as cnt FROM ins_invrepair WHERE end_repair IS NOT NULL GROUP BY yr ORDER BY yr",
        "type": "distribution",
    },
    {
        "id": 65,
        "q": "What is the average repair duration in days?",
        "sql": "SELECT AVG(DATEDIFF(end_repair, start_repair)) FROM ins_invrepair WHERE start_repair IS NOT NULL AND end_repair IS NOT NULL",
        "type": "numeric",
    },

    # === Category 6: Joins and relationships (66-80) ===
    {
        "id": 66,
        "q": "How many assessments are linked to each damage? Show the distribution.",
        "sql": "SELECT cnt, COUNT(*) as freq FROM (SELECT damage_id, COUNT(*) as cnt FROM ins_opis GROUP BY damage_id) t GROUP BY cnt ORDER BY cnt",
        "type": "distribution",
    },
    {
        "id": 67,
        "q": "How many damages have no associated assessment (opis)?",
        "sql": "SELECT COUNT(*) FROM ins_damages d LEFT JOIN ins_opis o ON d.damage_id = o.damage_id WHERE o.opis_id IS NULL",
        "type": "count",
    },
    {
        "id": 68,
        "q": "What is the average total_cost per car_class (join cars and damages via opis)?",
        "sql": "SELECT c.car_class, AVG(d.total_cost) as avg_cost FROM ins_opis o JOIN ins_damages d ON o.damage_id = d.damage_id JOIN ins_cars c ON o.car_id = c.car_id GROUP BY c.car_class ORDER BY c.car_class",
        "type": "distribution",
    },
    {
        "id": 69,
        "q": "How many unique cars have had damage claims?",
        "sql": "SELECT COUNT(DISTINCT car_id) FROM ins_opis",
        "type": "count",
    },
    {
        "id": 70,
        "q": "Which cars have had the most damage claims?",
        "sql": "SELECT car_id, COUNT(*) as cnt FROM ins_opis GROUP BY car_id ORDER BY cnt DESC LIMIT 5",
        "type": "top_n",
    },
    {
        "id": 71,
        "q": "What is the total invoice expense value per expense type?",
        "sql": "SELECT et.et_name, SUM(e.value_vat) as total FROM ins_mc_invexpenses e JOIN inv_exptypes et ON e.expense_type = et.exptype_id GROUP BY et.et_name ORDER BY total DESC",
        "type": "distribution",
    },
    {
        "id": 72,
        "q": "How many parts were replaced (part_new=1) vs repaired (part_repair>0) in assessments?",
        "sql": "SELECT SUM(CASE WHEN part_new = 1 THEN 1 ELSE 0 END) as replaced, SUM(CASE WHEN part_repair > 0 THEN 1 ELSE 0 END) as repaired FROM ins_opis_rows",
        "type": "comparison",
    },
    {
        "id": 73,
        "q": "What is the average total cost per car year group?",
        "sql": "SELECT car_yeargroup, AVG(total_cost) as avg_cost FROM ins_damages GROUP BY car_yeargroup ORDER BY car_yeargroup",
        "type": "distribution",
    },
    {
        "id": 74,
        "q": "How many repairs per car make (car_make_name)?",
        "sql": "SELECT car_make_name, COUNT(*) as cnt FROM ins_invrepair GROUP BY car_make_name ORDER BY cnt DESC",
        "type": "distribution",
    },
    {
        "id": 75,
        "q": "What is the total repair cost vs paint cost in damages?",
        "sql": "SELECT SUM(repairs_cost) as total_repair, SUM(paints_cost) as total_paint FROM ins_damages",
        "type": "comparison",
    },
    {
        "id": 76,
        "q": "How many opis rows reference each part? Show top 10 parts.",
        "sql": "SELECT p.part_name, COUNT(*) as cnt FROM ins_opis_rows r JOIN ins_partsindex p ON r.part_id = p.part_id GROUP BY p.part_name ORDER BY cnt DESC LIMIT 10",
        "type": "top_n",
    },
    {
        "id": 77,
        "q": "What is the average number of damaged parts per claim?",
        "sql": "SELECT AVG(cnt) FROM (SELECT opis_id, COUNT(*) as cnt FROM ins_opis_rows GROUP BY opis_id) t",
        "type": "numeric",
    },
    {
        "id": 78,
        "q": "How many invoice calculations exist per opis?",
        "sql": "SELECT cnt, COUNT(*) as freq FROM (SELECT opis_id, COUNT(*) as cnt FROM ins_mc_invcalc GROUP BY opis_id) t GROUP BY cnt ORDER BY cnt",
        "type": "distribution",
    },
    {
        "id": 79,
        "q": "What percentage of damages are regress cases?",
        "sql": "SELECT ROUND(100.0 * SUM(CASE WHEN damage_isregress = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) FROM ins_damages",
        "type": "numeric",
    },
    {
        "id": 80,
        "q": "How many horizon models exist per brand (top 10)?",
        "sql": "SELECT b.brand_name, COUNT(*) as cnt FROM srv_mc_horizon_model m JOIN srv_mc_horizon_brand b ON m.brand_id = b.brand_id AND m.category_id = b.category_id GROUP BY b.brand_name ORDER BY cnt DESC LIMIT 10",
        "type": "top_n",
    },

    # === Category 7: Complex / multi-step (81-90) ===
    {
        "id": 81,
        "q": "What is the cost breakdown (parts, repairs, mounts, paints, transport, other) as a percentage of total cost across all damages?",
        "sql": "SELECT ROUND(100*SUM(newparts_cost)/SUM(total_cost),1) as pct_parts, ROUND(100*SUM(repairs_cost)/SUM(total_cost),1) as pct_repairs, ROUND(100*SUM(mounts_cost)/SUM(total_cost),1) as pct_mounts, ROUND(100*SUM(paints_cost)/SUM(total_cost),1) as pct_paints, ROUND(100*SUM(transport_cost)/SUM(total_cost),1) as pct_transport, ROUND(100*SUM(other_cost)/SUM(total_cost),1) as pct_other FROM ins_damages WHERE total_cost > 0",
        "type": "distribution",
    },
    {
        "id": 82,
        "q": "What is the average total cost of damages per quarter (by damage_date)?",
        "sql": "SELECT YEAR(damage_date) as yr, QUARTER(damage_date) as q, AVG(total_cost) as avg_cost FROM ins_damages WHERE damage_date IS NOT NULL GROUP BY yr, q ORDER BY yr, q",
        "type": "distribution",
    },
    {
        "id": 83,
        "q": "How does the damage cost change with car age (years since first registration)?",
        "sql": "SELECT (YEAR(d.damage_date) - c.car_year) as age, AVG(d.total_cost) as avg_cost, COUNT(*) as cnt FROM ins_opis o JOIN ins_damages d ON o.damage_id = d.damage_id JOIN ins_cars c ON o.car_id = c.car_id WHERE d.damage_date IS NOT NULL AND c.car_year > 0 GROUP BY age HAVING cnt >= 5 ORDER BY age",
        "type": "distribution",
    },
    {
        "id": 84,
        "q": "What fraction of assessments use digital processing (opis_digital=1)?",
        "sql": "SELECT ROUND(100.0 * SUM(CASE WHEN opis_digital = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) FROM ins_opis",
        "type": "numeric",
    },
    {
        "id": 85,
        "q": "What is the median total cost of damage claims?",
        "sql": "SELECT AVG(total_cost) AS median_cost FROM (SELECT total_cost, ROW_NUMBER() OVER (ORDER BY total_cost) AS rn, COUNT(*) OVER () AS cnt FROM ins_damages WHERE total_cost > 0) sub WHERE rn IN (FLOOR((cnt+1)/2), CEIL((cnt+1)/2))",
        "type": "numeric",
    },
    {
        "id": 86,
        "q": "Which car makes have the highest average damage cost? Show top 5.",
        "sql": "SELECT m.mc_make_name, AVG(d.total_cost) as avg_cost, COUNT(*) as cnt FROM ins_opis o JOIN ins_damages d ON o.damage_id = d.damage_id JOIN ins_cars c ON o.car_id = c.car_id JOIN srv_mc_catalog_make m ON c.car_make = m.mc_make WHERE c.car_make > 0 GROUP BY m.mc_make_name HAVING cnt >= 3 ORDER BY avg_cost DESC LIMIT 5",
        "type": "top_n",
    },
    {
        "id": 87,
        "q": "What is the ratio of paint cost to total cost for damages where total_cost > 1000?",
        "sql": "SELECT ROUND(AVG(paints_cost / total_cost) * 100, 2) FROM ins_damages WHERE total_cost > 1000",
        "type": "numeric",
    },
    {
        "id": 88,
        "q": "How many claims have had at least one repair attempt that was sent to a service?",
        "sql": "SELECT COUNT(DISTINCT opis_id) FROM ins_invrepair",
        "type": "count",
    },
    {
        "id": 89,
        "q": "What is the total value of all invoice expenses by supplier (top 10 suppliers)?",
        "sql": "SELECT supplier_name, SUM(value_vat) as total FROM ins_mc_invexpenses WHERE supplier_name != '' GROUP BY supplier_name ORDER BY total DESC LIMIT 10",
        "type": "top_n",
    },
    {
        "id": 90,
        "q": "How many claims had items initially but items were later removed (items_count_initial > items_count_current)?",
        "sql": "SELECT COUNT(*) FROM ins_opis WHERE items_count_initial > items_count_current",
        "type": "count",
    },

    # === Category 8: Domain/EDA questions (91-100) ===
    {
        "id": 91,
        "q": "List all distinct car fuel types and how many cars use each.",
        "sql": "SELECT car_fuel, COUNT(*) as cnt FROM ins_cars GROUP BY car_fuel ORDER BY cnt DESC",
        "type": "distribution",
    },
    {
        "id": 92,
        "q": "What are all the distinct opis_status values and their counts?",
        "sql": "SELECT opis_status, COUNT(*) as cnt FROM ins_opis GROUP BY opis_status ORDER BY cnt DESC",
        "type": "distribution",
    },
    {
        "id": 93,
        "q": "Show the distribution of car_class values in the cars table.",
        "sql": "SELECT car_class, COUNT(*) as cnt FROM ins_cars GROUP BY car_class ORDER BY cnt DESC",
        "type": "distribution",
    },
    {
        "id": 94,
        "q": "List all horizon categories with their names.",
        "sql": "SELECT category_id, category_name FROM srv_mc_horizon_category WHERE category_name != '' ORDER BY category_name",
        "type": "list",
    },
    {
        "id": 95,
        "q": "How many cars have each number of doors?",
        "sql": "SELECT car_doors, COUNT(*) as cnt FROM ins_cars GROUP BY car_doors ORDER BY cnt DESC",
        "type": "distribution",
    },
    {
        "id": 96,
        "q": "What is the distribution of claim_type in assessments?",
        "sql": "SELECT claim_type, COUNT(*) as cnt FROM ins_opis GROUP BY claim_type ORDER BY cnt DESC",
        "type": "distribution",
    },
    {
        "id": 97,
        "q": "How many distinct currencies are used in damages?",
        "sql": "SELECT calc_currency_code, COUNT(*) as cnt FROM ins_damages WHERE calc_currency_code IS NOT NULL GROUP BY calc_currency_code",
        "type": "distribution",
    },
    {
        "id": 98,
        "q": "What is the average, min, and max total_cost grouped by damage year?",
        "sql": "SELECT YEAR(damage_date) as yr, AVG(total_cost) as avg_cost, MIN(total_cost) as min_cost, MAX(total_cost) as max_cost FROM ins_damages WHERE damage_date IS NOT NULL GROUP BY yr ORDER BY yr",
        "type": "distribution",
    },
    {
        "id": 99,
        "q": "How many generated documents exist per document type?",
        "sql": "SELECT doc_type, COUNT(*) as cnt FROM ins_gendocs GROUP BY doc_type ORDER BY cnt DESC",
        "type": "distribution",
    },
    {
        "id": 100,
        "q": "What is the total cost and count of damages per damage_place (top 10 places)?",
        "sql": "SELECT damage_place, COUNT(*) as cnt, SUM(total_cost) as total FROM ins_damages WHERE damage_place IS NOT NULL AND damage_place != '' GROUP BY damage_place ORDER BY cnt DESC LIMIT 10",
        "type": "top_n",
    },
]


def compute_ground_truth(engine: sqlalchemy.Engine) -> dict[int, dict]:
    """Run all ground truth SQL queries and store results."""
    results = {}
    with engine.connect() as conn:
        for q in QUESTIONS:
            qid = q["id"]
            try:
                rows = conn.execute(sqlalchemy.text(q["sql"])).fetchall()
                if q["type"] == "count":
                    results[qid] = {"value": rows[0][0], "rows": rows}
                elif q["type"] == "numeric":
                    val = rows[0][0]
                    results[qid] = {"value": float(val) if val is not None else None, "rows": rows}
                elif q["type"] == "value":
                    results[qid] = {"value": str(rows[0][0]), "rows": rows}
                else:
                    results[qid] = {"value": None, "rows": rows}
            except Exception as e:
                results[qid] = {"value": None, "error": str(e), "rows": []}
                logger.warning("SQL error for Q%d: %s", qid, e)
    return results


async def run_agent_question(question: str, registry: SourceRegistry, llm) -> dict:
    """Run a single question through the agent."""
    callbacks = CallbackManager()
    events = []
    callbacks.add_listener(lambda e: events.append({"type": e.type, "data": e.data}))

    start = time.time()
    try:
        state = await run_agent(
            question=question,
            registry=registry,
            llm=llm,
            callbacks=callbacks,
            experience_cache=_experience_cache,
        )
        elapsed = time.time() - start
        return {
            "response": state.get("response", ""),
            "mode": state.get("query_mode", ""),
            "artifacts": state.get("artifacts", []),
            "execution_log": state.get("execution_log", []),
            "elapsed_s": round(elapsed, 2),
            "events": events,
            "error": None,
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
        }


def evaluate_response(question: dict, ground_truth: dict, agent_result: dict) -> dict:
    """Evaluate the agent response against ground truth."""
    qtype = question["type"]
    response = agent_result.get("response", "")
    gt = ground_truth

    result = {
        "id": question["id"],
        "question": question["q"],
        "type": qtype,
        "mode": agent_result.get("mode", ""),
        "elapsed_s": agent_result.get("elapsed_s", 0),
        "error": agent_result.get("error"),
        "response_length": len(response) if response else 0,
    }

    if agent_result.get("error"):
        result["score"] = 0
        result["reason"] = f"Agent error: {agent_result['error']}"
        return result

    if not response or response.strip() == "":
        result["score"] = 0
        result["reason"] = "Empty response"
        return result

    # Check for failure responses — only if "could not" appears near the start
    # (not buried in a long substantive answer as a passing remark)
    lower_resp = response.lower()
    first_200 = lower_resp[:200]
    if ("could not" in first_200 and ("calculate" in first_200 or "determine" in first_200 or "plan" in first_200)):
        result["score"] = 0
        result["reason"] = f"Error response: {response[:100]}"
        return result

    # Type-specific evaluation
    if qtype == "count" and gt.get("value") is not None:
        expected = int(gt["value"])
        expected_str = str(expected)
        # Also check comma-formatted (e.g. "1,105" for 1105)
        expected_comma = f"{expected:,}"
        if expected_str in response or expected_comma in response:
            result["score"] = 1
            result["reason"] = f"Contains expected count {expected}"
        else:
            # Check if the number appears with other formatting (markdown bold, etc)
            found = _check_numeric_in_response(response, float(expected), tolerance=0.001)
            if found:
                result["score"] = 1
                result["reason"] = f"Contains expected count ~{expected}"
            else:
                result["score"] = 0
                result["reason"] = f"Expected {expected}, not found in response"
                result["expected"] = expected

    elif qtype == "numeric" and gt.get("value") is not None:
        expected = gt["value"]
        # Check if a close number appears in the response
        found = _check_numeric_in_response(response, expected)
        if found:
            result["score"] = 1
            result["reason"] = f"Contains expected numeric ~{expected:.2f}"
        else:
            result["score"] = 0
            result["reason"] = f"Expected ~{expected:.2f}, not found"
            result["expected"] = round(expected, 2)

    elif qtype == "value" and gt.get("value") is not None:
        expected = str(gt["value"])
        if expected in response:
            result["score"] = 1
            result["reason"] = f"Contains expected value {expected}"
        else:
            # Try alternative date formats
            if _check_date_in_response(expected, response):
                result["score"] = 1
                result["reason"] = f"Contains expected value {expected} (alt format)"
            else:
                result["score"] = 0
                result["reason"] = f"Expected {expected}, not found"
                result["expected"] = expected

    elif qtype in ("top_n", "distribution", "list", "comparison"):
        # Check for key GT values in the response (not just length)
        gt_rows = gt.get("rows", [])
        if gt_rows:
            # Check if key values from GT appear in response
            matched = 0
            checked = 0
            for row in gt_rows[:5]:  # Check first 5 GT rows
                for val in row:
                    if val is None:
                        continue
                    val_str = str(val)
                    if len(val_str) < 2 or val_str in ("0", "1"):
                        continue  # Skip trivial values
                    checked += 1
                    # Check both raw and comma-formatted numbers
                    if val_str in response:
                        matched += 1
                    elif isinstance(val, (int, float)):
                        try:
                            if f"{int(val):,}" in response:
                                matched += 1
                            elif _check_numeric_in_response(response, float(val), tolerance=0.05):
                                matched += 1
                        except (ValueError, OverflowError):
                            pass
            if checked > 0 and matched / checked >= 0.3:
                result["score"] = 1
                result["reason"] = f"Contains {matched}/{checked} key GT values"
            elif len(response) > 50:
                result["score"] = 1
                result["reason"] = "Non-trivial response generated"
            else:
                result["score"] = 0.5
                result["reason"] = f"Short response, matched {matched}/{checked} GT values"
        elif len(response) > 50:
            result["score"] = 1
            result["reason"] = "Non-trivial response generated"
        else:
            result["score"] = 0.5
            result["reason"] = "Short response, may be incomplete"
    else:
        result["score"] = 0.5
        result["reason"] = "Could not verify"

    result["ground_truth"] = str(gt.get("value", ""))[:200]
    result["response_preview"] = response[:300] if response else ""

    return result


def _check_date_in_response(expected_date: str, response: str) -> bool:
    """Check if a date appears in any common format in the response."""
    from datetime import datetime
    try:
        dt = datetime.strptime(expected_date, "%Y-%m-%d")
    except ValueError:
        return False

    formats = [
        dt.strftime("%B %d, %Y"),       # February 17, 2021
        dt.strftime("%B %-d, %Y"),       # February 17, 2021 (no zero pad)
        dt.strftime("%b %d, %Y"),        # Feb 17, 2021
        dt.strftime("%d/%m/%Y"),         # 17/02/2021
        dt.strftime("%m/%d/%Y"),         # 02/17/2021
        dt.strftime("%Y-%m-%d"),         # 2021-02-17
        dt.strftime("%d.%m.%Y"),         # 17.02.2021
    ]
    return any(fmt in response for fmt in formats)


def _check_numeric_in_response(response: str, expected: float, tolerance: float = 0.10) -> bool:
    """Check if a number close to expected appears in the response."""
    import re

    # Special handling for zero — check word forms
    if expected == 0:
        zero_words = {"zero", "no ", "none", "0"}
        lower_resp = response.lower()
        if any(w in lower_resp for w in zero_words):
            return True

    # Remove commas from the response for number matching, find all numbers
    clean = response.replace(",", "")
    numbers = re.findall(r'\d+\.?\d*', clean)
    for num_str in numbers:
        try:
            num = float(num_str)
            if expected == 0:
                if num == 0:
                    return True
            elif abs(num - expected) / abs(expected) <= tolerance:
                return True
        except ValueError:
            continue
    return False


async def main():
    db_url = os.environ.get("MCPDB_DATABASE_URL")
    gemini_key = os.environ.get("GEMINI_API_KEY")

    if not db_url:
        print("ERROR: MCPDB_DATABASE_URL not set")
        sys.exit(1)
    if not gemini_key:
        print("ERROR: GEMINI_API_KEY not set")
        sys.exit(1)

    print(f"Database: {db_url}")
    print(f"Questions: {len(QUESTIONS)}")
    print()

    # Compute ground truth
    print("Computing ground truth SQL answers...")
    engine = sqlalchemy.create_engine(db_url)
    ground_truth = compute_ground_truth(engine)
    engine.dispose()

    # Save ground truth
    gt_path = Path(__file__).parent / "ground_truth.json"
    gt_serializable = {}
    for qid, gt in ground_truth.items():
        gt_serializable[qid] = {
            "value": str(gt.get("value")) if gt.get("value") is not None else None,
            "error": gt.get("error"),
            "row_count": len(gt.get("rows", [])),
        }
    gt_path.write_text(json.dumps(gt_serializable, indent=2, default=str))
    print(f"Ground truth saved to {gt_path}")

    # Set up agent
    print("Setting up agent...")
    registry = SourceRegistry()
    source = DatabaseSource(db_url)
    registry.add_source(source)

    llm = create_provider("gemini", "gemini-2.5-pro", gemini_key)
    print(f"LLM: gemini-2.5-pro")
    print()

    # Run all questions
    results = []
    scores = []
    errors = []

    for i, question in enumerate(QUESTIONS):
        qid = question["id"]
        print(f"[{i+1:3d}/100] Q{qid}: {question['q'][:60]}...", end=" ", flush=True)

        agent_result = await run_agent_question(question["q"], registry, llm)

        gt = ground_truth.get(qid, {})
        eval_result = evaluate_response(question, gt, agent_result)
        eval_result["agent_response"] = agent_result.get("response", "")[:1000]
        eval_result["execution_log"] = agent_result.get("execution_log", [])

        results.append(eval_result)
        scores.append(eval_result["score"])

        status = "PASS" if eval_result["score"] >= 1 else ("PARTIAL" if eval_result["score"] > 0 else "FAIL")
        print(f"{status} ({eval_result['elapsed_s']}s, {eval_result['mode']}) — {eval_result['reason'][:60]}")

        if eval_result["score"] < 1:
            errors.append(eval_result)

        # Rate limiting for Gemini API
        await asyncio.sleep(0.5)

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

    # Save full results
    results_path = Path(__file__).parent / "eval_results.json"
    results_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"\nFull results saved to {results_path}")

    # Save test dataset
    dataset_path = Path(__file__).parent / "test_dataset.json"
    dataset = {
        "database": db_url.split("@")[1] if "@" in db_url else db_url,
        "questions": QUESTIONS,
        "ground_truth": gt_serializable,
    }
    dataset_path.write_text(json.dumps(dataset, indent=2, default=str))
    print(f"Test dataset saved to {dataset_path}")

    # Print failures for investigation
    if errors:
        print(f"\n{'='*80}")
        print(f"FAILURES AND PARTIAL ({len(errors)}):")
        print(f"{'='*80}")
        for err in errors:
            print(f"\nQ{err['id']}: {err['question']}")
            print(f"  Type: {err['type']}, Mode: {err['mode']}, Score: {err['score']}")
            print(f"  Reason: {err['reason']}")
            if err.get('expected'):
                print(f"  Expected: {err['expected']}")
            print(f"  Response preview: {err.get('response_preview', '')[:200]}")

    registry.close_all()


if __name__ == "__main__":
    asyncio.run(main())
