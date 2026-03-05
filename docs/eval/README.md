# Eval Results Summary

**Run date:** No-cache eval
**LLM:** Gemini 2.5 Pro
**Cache:** Disabled

## Overall

| Metric | Value |
|--------|-------|
| **Total Questions** | 100 |
| **Pass** | 94 |
| **Partial** | 1 |
| **Fail** | 5 |
| **Pass Rate** | 94.0% |
| **Average Score** | 94.50% |
| **Total Time** | 3274s (54.6m) |

## By Category

| Category | Pass | Partial | Fail | Total | Rate |
|----------|------|---------|------|-------|------|
| Counts | 8 | 0 | 2 | 10 | 80% |
| Aggregation | 15 | 0 | 0 | 15 | 100% |
| Filtering | 15 | 0 | 0 | 15 | 100% |
| Top-N | 15 | 0 | 0 | 15 | 100% |
| Dates | 9 | 0 | 1 | 10 | 90% |
| Joins | 15 | 0 | 0 | 15 | 100% |
| Complex | 7 | 1 | 2 | 10 | 70% |
| Domain | 10 | 0 | 0 | 10 | 100% |

## By Mode

| Mode | Pass | Partial | Fail | Total | Avg Time |
|------|------|---------|------|-------|----------|
|  | 0 | 0 | 1 | 1 | 69.8s |
| quick | 4 | 0 | 0 | 4 | 11.3s |
| simple | 90 | 1 | 4 | 95 | 33.2s |

## By Question Type

| Type | Pass | Partial | Fail | Total | Rate |
|------|------|---------|------|-------|------|
| comparison | 2 | 0 | 0 | 2 | 100% |
| count | 29 | 0 | 2 | 31 | 94% |
| distribution | 19 | 0 | 1 | 20 | 95% |
| list | 1 | 0 | 0 | 1 | 100% |
| numeric | 18 | 1 | 2 | 21 | 86% |
| top_n | 22 | 0 | 0 | 22 | 100% |
| value | 3 | 0 | 0 | 3 | 100% |

## Failures

| QID | Question | Type | Category | Score | Reason |
|-----|----------|------|----------|-------|--------|
| [Q006](questions/q006.md) | How many car makes are in the catalog? | count | Counts | 0 | Expected 155, not found in response |
| [Q007](questions/q007.md) | How many car models exist in the catalog... | count | Counts | 0 | Expected 2261, not found in response |
| [Q062](questions/q062.md) | What is the average age of cars at the t... | numeric | Dates | 0 | Expected ~9.71, not found |
| [Q083](questions/q083.md) | How does the damage cost change with car... | distribution | Complex | 0 | Agent error: unhashable type: 'slice' |
| [Q085](questions/q085.md) | What is the median total cost of damage ... | numeric | Complex | 0.5 | Could not verify |
| [Q087](questions/q087.md) | What is the ratio of paint cost to total... | numeric | Complex | 0 | Expected ~30.85, not found |

## Timing

| Stat | Value |
|------|-------|
| Min | 4.3s |
| Max | 72.7s |
| Avg | 32.7s |
| Median | 30.3s |
| Total | 3274s (54.6m) |

## All Questions

- [PASS] [Q001](questions/q001.md): How many tables are in the database?
- [PASS] [Q002](questions/q002.md): How many cars are in the ins_cars table?
- [PASS] [Q003](questions/q003.md): How many damage claims exist?
- [PASS] [Q004](questions/q004.md): How many repair records are there?
- [PASS] [Q005](questions/q005.md): How many parts are in the parts index?
- [FAIL] [Q006](questions/q006.md): How many car makes are in the catalog?
- [FAIL] [Q007](questions/q007.md): How many car models exist in the catalog?
- [PASS] [Q008](questions/q008.md): How many expense types are defined?
- [PASS] [Q009](questions/q009.md): How many unique damage places are there?
- [PASS] [Q010](questions/q010.md): How many assessments (opis) exist?
- [PASS] [Q011](questions/q011.md): What is the total cost of all damage claims?
- [PASS] [Q012](questions/q012.md): What is the average total cost per damage claim?
- [PASS] [Q013](questions/q013.md): What is the maximum total cost of a single damage claim?
- [PASS] [Q014](questions/q014.md): What is the minimum non-zero total cost of a damage claim?
- [PASS] [Q015](questions/q015.md): What is the total compensation paid across all damages?
- [PASS] [Q016](questions/q016.md): What is the average premium (premium_main) across all damage
- [PASS] [Q017](questions/q017.md): What is the total newparts_cost across all damages?
- [PASS] [Q018](questions/q018.md): What is the total painting cost (paints_cost) across all dam
- [PASS] [Q019](questions/q019.md): What is the average repair cost per damage?
- [PASS] [Q020](questions/q020.md): How many damage claims have a total cost above 5000?
- [PASS] [Q021](questions/q021.md): What is the sum of transport costs across all damages?
- [PASS] [Q022](questions/q022.md): What is the average number of items per assessment (opis)?
- [PASS] [Q023](questions/q023.md): What is the maximum expected_value in the damages table?
- [PASS] [Q024](questions/q024.md): How many damage claims have compensation greater than zero?
- [PASS] [Q025](questions/q025.md): What is the total invoice calculation cost (from ins_mc_invc
- [PASS] [Q026](questions/q026.md): How many cars were manufactured in 2020?
- [PASS] [Q027](questions/q027.md): How many cars use diesel fuel (car_fuel=1)?
- [PASS] [Q028](questions/q028.md): How many damage claims are marked as regress (damage_isregre
- [PASS] [Q029](questions/q029.md): How many repairs have status 1000 (completed)?
- [PASS] [Q030](questions/q030.md): How many assessments have status 1000?
- [PASS] [Q031](questions/q031.md): How many cars have car_class = 3?
- [PASS] [Q032](questions/q032.md): How many damage claims happened in Sofia (damage_place conta
- [PASS] [Q033](questions/q033.md): How many supported car makes are in the catalog (mc_supporte
- [PASS] [Q034](questions/q034.md): How many cars have a non-empty chassis number?
- [PASS] [Q035](questions/q035.md): How many damage claims occurred in 2023?
- [PASS] [Q036](questions/q036.md): How many generated documents have file_deleted = 0?
- [PASS] [Q037](questions/q037.md): How many invoice calculations are of type 'mc'?
- [PASS] [Q038](questions/q038.md): How many opis rows have part_new = 1 (new parts)?
- [PASS] [Q039](questions/q039.md): How many damages have total_cost equal to zero?
- [PASS] [Q040](questions/q040.md): How many cars are of type 1?
- [PASS] [Q041](questions/q041.md): What are the top 5 most expensive damage claims by total_cos
- [PASS] [Q042](questions/q042.md): What are the 3 most common damage places?
- [PASS] [Q043](questions/q043.md): Which car year has the most vehicles?
- [PASS] [Q044](questions/q044.md): Which 5 car makes appear most often in repairs?
- [PASS] [Q045](questions/q045.md): What are the top 5 most frequently damaged parts (by part_id
- [PASS] [Q046](questions/q046.md): Which damage had the highest premium_main?
- [PASS] [Q047](questions/q047.md): What are the 5 most expensive invoice calculations (active o
- [PASS] [Q048](questions/q048.md): Which service_id has the most repairs?
- [PASS] [Q049](questions/q049.md): Which year had the most damage claims?
- [PASS] [Q050](questions/q050.md): What is the most common car_class in the cars table?
- [PASS] [Q051](questions/q051.md): Top 3 car makes by number of insured vehicles?
- [PASS] [Q052](questions/q052.md): Which 5 expense names are the most frequent in inv_expenses?
- [PASS] [Q053](questions/q053.md): Which damage place has the highest average total cost?
- [PASS] [Q054](questions/q054.md): Which opis has the most rows (damaged parts)?
- [PASS] [Q055](questions/q055.md): What is the longest repair duration (end_repair - start_repa
- [PASS] [Q056](questions/q056.md): What is the earliest damage date in the database?
- [PASS] [Q057](questions/q057.md): What is the latest damage date in the database?
- [PASS] [Q058](questions/q058.md): How many damages occurred per year? List all years.
- [PASS] [Q059](questions/q059.md): What is the average time between damage_date and damage_noti
- [PASS] [Q060](questions/q060.md): How many damage claims were filed in each month of 2022?
- [PASS] [Q061](questions/q061.md): What is the earliest car registration year?
- [FAIL] [Q062](questions/q062.md): What is the average age of cars at the time of damage?
- [PASS] [Q063](questions/q063.md): Which month has the most damage claims overall?
- [PASS] [Q064](questions/q064.md): How many repairs were completed (end_repair IS NOT NULL) per
- [PASS] [Q065](questions/q065.md): What is the average repair duration in days?
- [PASS] [Q066](questions/q066.md): How many assessments are linked to each damage? Show the dis
- [PASS] [Q067](questions/q067.md): How many damages have no associated assessment (opis)?
- [PASS] [Q068](questions/q068.md): What is the average total_cost per car_class (join cars and 
- [PASS] [Q069](questions/q069.md): How many unique cars have had damage claims?
- [PASS] [Q070](questions/q070.md): Which cars have had the most damage claims?
- [PASS] [Q071](questions/q071.md): What is the total invoice expense value per expense type?
- [PASS] [Q072](questions/q072.md): How many parts were replaced (part_new=1) vs repaired (part_
- [PASS] [Q073](questions/q073.md): What is the average total cost per car year group?
- [PASS] [Q074](questions/q074.md): How many repairs per car make (car_make_name)?
- [PASS] [Q075](questions/q075.md): What is the total repair cost vs paint cost in damages?
- [PASS] [Q076](questions/q076.md): How many opis rows reference each part? Show top 10 parts.
- [PASS] [Q077](questions/q077.md): What is the average number of damaged parts per claim?
- [PASS] [Q078](questions/q078.md): How many invoice calculations exist per opis?
- [PASS] [Q079](questions/q079.md): What percentage of damages are regress cases?
- [PASS] [Q080](questions/q080.md): How many horizon models exist per brand (top 10)?
- [PASS] [Q081](questions/q081.md): What is the cost breakdown (parts, repairs, mounts, paints, 
- [PASS] [Q082](questions/q082.md): What is the average total cost of damages per quarter (by da
- [FAIL] [Q083](questions/q083.md): How does the damage cost change with car age (years since fi
- [PASS] [Q084](questions/q084.md): What fraction of assessments use digital processing (opis_di
- [PARTIAL] [Q085](questions/q085.md): What is the median total cost of damage claims?
- [PASS] [Q086](questions/q086.md): Which car makes have the highest average damage cost? Show t
- [FAIL] [Q087](questions/q087.md): What is the ratio of paint cost to total cost for damages wh
- [PASS] [Q088](questions/q088.md): How many claims have had at least one repair attempt that wa
- [PASS] [Q089](questions/q089.md): What is the total value of all invoice expenses by supplier 
- [PASS] [Q090](questions/q090.md): How many claims had items initially but items were later rem
- [PASS] [Q091](questions/q091.md): List all distinct car fuel types and how many cars use each.
- [PASS] [Q092](questions/q092.md): What are all the distinct opis_status values and their count
- [PASS] [Q093](questions/q093.md): Show the distribution of car_class values in the cars table.
- [PASS] [Q094](questions/q094.md): List all horizon categories with their names.
- [PASS] [Q095](questions/q095.md): How many cars have each number of doors?
- [PASS] [Q096](questions/q096.md): What is the distribution of claim_type in assessments?
- [PASS] [Q097](questions/q097.md): How many distinct currencies are used in damages?
- [PASS] [Q098](questions/q098.md): What is the average, min, and max total_cost grouped by dama
- [PASS] [Q099](questions/q099.md): How many generated documents exist per document type?
- [PASS] [Q100](questions/q100.md): What is the total cost and count of damages per damage_place
