"""Test questions for autonomous eval with observer monitoring.

Three data sources:
- bgins: MySQL DB (21 tables, Bulgarian insurance claims)
- qala: CSV (464K rows, Qala MTPL insurance policies)
- lithuania: CSV (312K rows, Lithuanian MTPL insurance)

Questions tagged with expected mode and complexity.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EvalQuestion:
    """A question for autonomous evaluation."""
    id: str
    question: str
    source: str  # bgins, qala, lithuania
    expected_mode: str  # quick, simple, optimization, extended, deep
    max_time_s: int  # maximum acceptable time in seconds
    category: str  # schema, aggregation, distribution, correlation, deep_analysis


# --- Database questions (bgins) ---

DB_QUESTIONS = [
    EvalQuestion("db01", "How many tables are in the database?", "bgins", "quick", 15, "schema"),
    EvalQuestion("db02", "How many records are in ins_cars?", "bgins", "quick", 15, "schema"),
    EvalQuestion("db03", "What are the column names in ins_damages?", "bgins", "quick", 15, "schema"),
    EvalQuestion("db04", "Show 5 sample rows from ins_opis", "bgins", "simple", 30, "schema"),
    EvalQuestion("db05", "What distinct damage types exist in ins_damages?", "bgins", "simple", 30, "schema"),

    EvalQuestion("db06", "What car brands appear most frequently in ins_cars?", "bgins", "simple", 40, "aggregation"),
    EvalQuestion("db07", "How many claims per year are there?", "bgins", "simple", 40, "aggregation"),
    EvalQuestion("db08", "What is the average repair cost?", "bgins", "simple", 30, "aggregation"),
    EvalQuestion("db09", "Top 10 most expensive repairs", "bgins", "simple", 40, "aggregation"),
    EvalQuestion("db10", "Average repair cost by car brand", "bgins", "simple", 45, "aggregation"),

    EvalQuestion("db11", "What is the distribution of damage types in ins_damages?", "bgins", "simple", 45, "distribution"),
    EvalQuestion("db12", "Show the distribution of car ages in ins_cars", "bgins", "simple", 45, "distribution"),
    EvalQuestion("db13", "Monthly trend of claims count across all years", "bgins", "optimization_required", 90, "distribution"),
    EvalQuestion("db14", "Compare repair costs across different vehicle categories", "bgins", "optimization_required", 90, "correlation"),
    EvalQuestion("db15", "What percentage of cars have more than one claim?", "bgins", "simple", 45, "aggregation"),

    EvalQuestion("db16", "Correlation between car age and total claim cost", "bgins", "optimization_required", 120, "correlation"),
    EvalQuestion("db17", "Which repair shops have the highest average cost?", "bgins", "simple", 60, "aggregation"),
    EvalQuestion("db18", "Analyze seasonal patterns in claims by month", "bgins", "optimization_required", 120, "distribution"),
    EvalQuestion("db19", "Compare all vehicle makes by average claim frequency and severity", "bgins", "extended", 240, "deep_analysis"),
    EvalQuestion("db20", "Full statistical profile of the claims pipeline — frequency, severity, and cost distribution", "bgins", "deep", 600, "deep_analysis"),
]

# --- CSV questions (Qala MTPL) ---

QALA_QUESTIONS = [
    EvalQuestion("qa01", "How many rows and columns are in this dataset?", "qala", "quick", 15, "schema"),
    EvalQuestion("qa02", "What are the column names?", "qala", "quick", 15, "schema"),
    EvalQuestion("qa03", "Show 5 sample rows", "qala", "simple", 30, "schema"),
    EvalQuestion("qa04", "What is the average UnderwritingPremium?", "qala", "simple", 30, "aggregation"),
    EvalQuestion("qa05", "How many unique PolicyInsuranceType values exist?", "qala", "simple", 30, "aggregation"),

    EvalQuestion("qa06", "Distribution of VehicleType", "qala", "simple", 40, "distribution"),
    EvalQuestion("qa07", "Top 10 car brands by policy count", "qala", "simple", 40, "aggregation"),
    EvalQuestion("qa08", "Average claim amount by vehicle age group (0-5, 5-10, 10-15, 15+)", "qala", "simple", 60, "aggregation"),
    EvalQuestion("qa09", "What percentage of policies have at least one claim?", "qala", "simple", 40, "aggregation"),
    EvalQuestion("qa10", "Premium distribution statistics (mean, median, p25, p75, min, max)", "qala", "simple", 45, "distribution"),

    EvalQuestion("qa11", "Claim frequency by PolicyInsuranceClass", "qala", "simple", 45, "aggregation"),
    EvalQuestion("qa12", "Compare earned premium vs claim amount by insurance class", "qala", "optimization_required", 90, "correlation"),
    EvalQuestion("qa13", "Monthly policy issuance trend", "qala", "simple", 60, "distribution"),
    EvalQuestion("qa14", "Top 20 vehicle models by loss ratio (claim amount / earned premium)", "qala", "optimization_required", 90, "correlation"),
    EvalQuestion("qa15", "Risk profile: claim frequency and severity by vehicle category", "qala", "optimization_required", 120, "deep_analysis"),
]

# --- CSV questions (Lithuania MTPL) ---

LT_QUESTIONS = [
    EvalQuestion("lt01", "How many rows are in this dataset?", "lithuania", "quick", 15, "schema"),
    EvalQuestion("lt02", "List all column names", "lithuania", "quick", 15, "schema"),
    EvalQuestion("lt03", "Average GWP3 value", "lithuania", "simple", 30, "aggregation"),
    EvalQuestion("lt04", "How many unique vehicle types are there?", "lithuania", "simple", 30, "aggregation"),
    EvalQuestion("lt05", "Show 5 sample rows", "lithuania", "simple", 30, "schema"),

    EvalQuestion("lt06", "Distribution of SalesChannel", "lithuania", "simple", 40, "distribution"),
    EvalQuestion("lt07", "Policy count by Holder_address_region", "lithuania", "simple", 45, "aggregation"),
    EvalQuestion("lt08", "Average premium by BonusMalus_LTAB class", "lithuania", "simple", 45, "aggregation"),
    EvalQuestion("lt09", "Renewal rate (percentage of Renewal='Y')", "lithuania", "simple", 40, "aggregation"),
    EvalQuestion("lt10", "Top 10 vehicle brands by policy count", "lithuania", "simple", 45, "aggregation"),

    EvalQuestion("lt11", "Compare premium between private and corporate holders", "lithuania", "simple", 45, "aggregation"),
    EvalQuestion("lt12", "Monthly policy issuance trend over all years", "lithuania", "optimization_required", 90, "distribution"),
    EvalQuestion("lt13", "Distribution of deductible amounts (Deductuble_damage)", "lithuania", "simple", 45, "distribution"),
    EvalQuestion("lt14", "Average GWP by vehicle power group", "lithuania", "optimization_required", 90, "correlation"),
    EvalQuestion("lt15", "Fleet vs non-fleet policies: count and average premium comparison", "lithuania", "simple", 60, "aggregation"),
]


ALL_QUESTIONS = DB_QUESTIONS + QALA_QUESTIONS + LT_QUESTIONS

# Quick subsets for targeted testing
QUICK_ONLY = [q for q in ALL_QUESTIONS if q.expected_mode == "quick"]
SIMPLE_ONLY = [q for q in ALL_QUESTIONS if q.expected_mode == "simple"]
COMPLEX_ONLY = [q for q in ALL_QUESTIONS if q.expected_mode in ("optimization_required", "extended", "deep")]
