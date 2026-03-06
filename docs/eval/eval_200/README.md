# Extended Eval Results (Q101-Q300)

**Questions:** 200 (Q101-Q300)  
**LLM:** Gemini 2.5 Pro  
**Cache:** Disabled  

## Overall Results

| Metric | Value |
|--------|-------|
| **Pass** | 170 (85.0%) |
| **Partial** | 0 |
| **Fail** | 30 |
| **Average Score** | 85.00% |
| **Total Time** | 9292s (154.9m) |

## By Category

| Category | Description | Pass | Fail | Total | Rate |
|----------|-------------|------|------|-------|------|
| Frequency | Claims frequency, trends, and seasonal p | 17 | 3 | 20 | 85% |
| Cost | MC estimate cost severity, structure, an | 19 | 6 | 25 | 76% |
| Parts | Damage lines, part resolution, repair se | 19 | 1 | 20 | 95% |
| Supplier | Expense analysis, supplier concentration | 17 | 3 | 20 | 85% |
| Repair | Repair shop performance, cycle time, com | 24 | 1 | 25 | 96% |
| MC_vs_N24 | Regulatory (N24) vs catalog (MC) estimat | 10 | 5 | 15 | 67% |
| CycleTime | Claim lifecycle timing and process analy | 14 | 6 | 20 | 70% |
| DataQuality | Referential integrity, domain constraint | 19 | 1 | 20 | 95% |
| Geographic | Location-based cost and frequency analys | 15 | 0 | 15 | 100% |
| Complex | Multi-table actuarial analysis, segmenta | 16 | 4 | 20 | 80% |

## By Question Type

| Type | Pass | Fail | Total | Rate |
|------|------|------|-------|------|
| comparison | 10 | 0 | 10 | 100% |
| count | 39 | 18 | 57 | 68% |
| distribution | 64 | 1 | 65 | 98% |
| numeric | 31 | 11 | 42 | 74% |
| top_n | 26 | 0 | 26 | 100% |

## Failures

| QID | Question | Category | Type | Score | Reason |
|-----|----------|----------|------|-------|--------|
| [Q113](questions/q113.md) | What is the average number of claim... | Frequency | numeric | 0 | Expected ~1.19, not found |
| [Q114](questions/q114.md) | How many claims were filed within 7... | Frequency | count | 0 | Expected 2012, not found in respons |
| [Q115](questions/q115.md) | How many claims were filed more tha... | Frequency | count | 0 | Expected 19, not found in response |
| [Q126](questions/q126.md) | What is the average parts cost shar... | Cost | numeric | 0 | Expected ~21.02, not found |
| [Q127](questions/q127.md) | What is the average paint cost shar... | Cost | numeric | 0 | Expected ~53.02, not found |
| [Q128](questions/q128.md) | How many claims are 'paint heavy' (... | Cost | count | 0 | Expected 876, not found in response |
| [Q129](questions/q129.md) | How many claims are 'parts heavy' (... | Cost | count | 0 | Expected 241, not found in response |
| [Q142](questions/q142.md) | How many latest MC estimates have a... | Cost | count | 0 | Expected 5, not found in response |
| [Q144](questions/q144.md) | What is the average MC estimated co... | Cost | numeric | 0 | Expected ~2071.09, not found |
| [Q162](questions/q162.md) | How many distinct parts are always ... | Parts | count | 0 | Expected 797, not found in response |
| [Q171](questions/q171.md) | What is the average number of expen... | Supplier | numeric | 0 | Expected ~14.09, not found |
| [Q175](questions/q175.md) | What percentage of total expense va... | Supplier | numeric | 0 | Expected ~28.23, not found |
| [Q183](questions/q183.md) | What is the average total expense v... | Supplier | numeric | 0 | Expected ~227.10, not found |
| [Q210](questions/q210.md) | How many claims have both a repair ... | Repair | count | 0 | Expected 835, not found in response |
| [Q213](questions/q213.md) | For claims with both MC and N24, wh... | MC_vs_N24 | numeric | 0 | Expected ~46.00, not found |
| [Q214](questions/q214.md) | How many claims have N24 estimate e... | MC_vs_N24 | count | 0 | Expected 7, not found in response |
| [Q215](questions/q215.md) | How many claims have MC estimate ex... | MC_vs_N24 | count | 0 | Expected 16, not found in response |
| [Q216](questions/q216.md) | What is the average MC/N24 cost rat... | MC_vs_N24 | numeric | 0 | Expected ~1.16, not found |
| [Q223](questions/q223.md) | What is the average N24 estimated t... | MC_vs_N24 | numeric | 0 | Expected ~552.67, not found |
| [Q229](questions/q229.md) | How many claims were filed on the s... | CycleTime | count | 0 | Expected 170, not found in response |
| [Q230](questions/q230.md) | How many claims were filed more tha... | CycleTime | count | 0 | Expected 6, not found in response |
| [Q235](questions/q235.md) | How many claims have 3 or more MC e... | CycleTime | count | 0 | Expected 213, not found in response |
| [Q239](questions/q239.md) | How many repairs have a start_repai... | CycleTime | count | 0 | Expected 0, not found in response |
| [Q241](questions/q241.md) | What is the monthly average filing ... | CycleTime | distribution | 0 | Agent error: unhashable type: 'slic |
| [Q242](questions/q242.md) | How many claims have generated docu... | CycleTime | count | 0 | Expected 848, not found in response |
| [Q255](questions/q255.md) | How many opis records reference a c... | DataQuality | count | 0 | Expected 0, not found in response |
| [Q281](questions/q281.md) | How many claims have an MC estimate... | Complex | count | 0 | Expected 129, not found in response |
| [Q282](questions/q282.md) | How many claims are missing MC esti... | Complex | count | 0 | Expected 855, not found in response |
| [Q291](questions/q291.md) | What is the ratio of MC estimated c... | Complex | numeric | 0 | Expected ~2.23, not found |
| [Q294](questions/q294.md) | How many claims have both generated... | Complex | count | 0 | Expected 1286, not found in respons |

## Question Index


### Frequency

- [PASS] [Q101](questions/q101.md): How many claims were opened per month? Show month and count.
- [PASS] [Q102](questions/q102.md): How many claims were opened per quarter? Show year, quarter,
- [PASS] [Q103](questions/q103.md): How many claims were opened per year?
- [PASS] [Q104](questions/q104.md): How many claims exist for each damage type (damage_typeid)?
- [PASS] [Q105](questions/q105.md): How many claims exist for each claim_type?
- [PASS] [Q106](questions/q106.md): How many damage events occurred on each day of the week?
- [PASS] [Q107](questions/q107.md): What is the seasonal pattern of damage events by month of ye
- [PASS] [Q108](questions/q108.md): What is the average filing lag in days between the damage da
- [PASS] [Q109](questions/q109.md): What is the year-over-year growth in claim count? Show each 
- [PASS] [Q110](questions/q110.md): How many claims were opened per month in 2023?
- [PASS] [Q111](questions/q111.md): How many claims were opened per quarter in 2024?
- [PASS] [Q112](questions/q112.md): How many claims per damage_typeid were there in each year?
- [FAIL] [Q113](questions/q113.md): What is the average number of claims per day across the enti
- [FAIL] [Q114](questions/q114.md): How many claims were filed within 7 days of the damage event
- [FAIL] [Q115](questions/q115.md): How many claims were filed more than 30 days after the damag
- [PASS] [Q116](questions/q116.md): How many claims with a non-zero total cost were filed per mo
- [PASS] [Q117](questions/q117.md): How many claims with damage_typeid = 0 were there per year?
- [PASS] [Q118](questions/q118.md): What is the distribution of claims per car? How many cars ha
- [PASS] [Q119](questions/q119.md): How many claims were opened per month in 2025?
- [PASS] [Q120](questions/q120.md): What is the distribution of claim filing hour of day (from o

### Cost

- [PASS] [Q121](questions/q121.md): What is the average MC estimated total cost by car brand?
- [PASS] [Q122](questions/q122.md): What is the average MC estimated total cost by damage type?
- [PASS] [Q123](questions/q123.md): What is the MC estimate cost structure? Show the average sha
- [PASS] [Q124](questions/q124.md): How many claims have a latest MC estimate above 5000 BGN?
- [PASS] [Q125](questions/q125.md): How many claims have a latest MC estimate above 10000 BGN?
- [FAIL] [Q126](questions/q126.md): What is the average parts cost share (newparts_cost / total_
- [FAIL] [Q127](questions/q127.md): What is the average paint cost share (paints_cost / total_co
- [FAIL] [Q128](questions/q128.md): How many claims are 'paint heavy' (paint share > 40% of tota
- [FAIL] [Q129](questions/q129.md): How many claims are 'parts heavy' (parts share > 60% of tota
- [PASS] [Q130](questions/q130.md): What is the average MC estimated cost by car year group?
- [PASS] [Q131](questions/q131.md): What is the average MC estimated cost by claim type?
- [PASS] [Q132](questions/q132.md): Which top 5 car brands have the highest average MC estimated
- [PASS] [Q133](questions/q133.md): What is the average repair labor hours from latest MC estima
- [PASS] [Q134](questions/q134.md): What is the average total labor hours (repair + mount + pain
- [PASS] [Q135](questions/q135.md): What is the average MC estimated total cost by year of claim
- [PASS] [Q136](questions/q136.md): What is the average mount cost share from latest MC estimate
- [PASS] [Q137](questions/q137.md): What is the average MC estimated total cost grouped by numbe
- [PASS] [Q138](questions/q138.md): What is the average overall discount (service_discall) from 
- [PASS] [Q139](questions/q139.md): What is the distribution of MC estimated total cost by range
- [PASS] [Q140](questions/q140.md): How does the average latest MC estimated cost compare to the
- [PASS] [Q141](questions/q141.md): What is the average VAT sum from latest MC estimates?
- [FAIL] [Q142](questions/q142.md): How many latest MC estimates have a total cost of zero?
- [PASS] [Q143](questions/q143.md): What is the 90th percentile (P90) of MC estimated total cost
- [FAIL] [Q144](questions/q144.md): What is the average MC estimated cost for claims that have a
- [PASS] [Q145](questions/q145.md): What is the average 'other cost' from latest MC estimates?

### Parts

- [PASS] [Q146](questions/q146.md): What are the top 10 most frequently damaged parts? Resolve p
- [PASS] [Q147](questions/q147.md): What is the parts catalog source distribution? How many opis
- [PASS] [Q148](questions/q148.md): What is the total count of replacement lines (part_new IN (1
- [PASS] [Q149](questions/q149.md): What is the repair severity distribution? Show counts for pa
- [PASS] [Q150](questions/q150.md): What is the average number of damaged items (opis_rows) per 
- [PASS] [Q151](questions/q151.md): How many claims have exactly 1 damaged part?
- [PASS] [Q152](questions/q152.md): How many claims have more than 10 damaged parts?
- [PASS] [Q153](questions/q153.md): What are the top 5 parts most frequently replaced (part_new=
- [PASS] [Q154](questions/q154.md): What are the top 5 most frequently painted parts (part_paint
- [PASS] [Q155](questions/q155.md): How many parts appear in both a replacement role (part_new=1
- [PASS] [Q156](questions/q156.md): What is the average quantity per opis_row?
- [PASS] [Q157](questions/q157.md): What are the top 5 parts by major repair count (part_repair=
- [PASS] [Q158](questions/q158.md): What percentage of opis_rows have part_paint=1?
- [PASS] [Q159](questions/q159.md): What is the paint frequency (share of lines with part_paint=
- [PASS] [Q160](questions/q160.md): What is the average number of paint lines (part_paint=1) per
- [PASS] [Q161](questions/q161.md): What is the distribution of damage line counts per claim? Sh
- [FAIL] [Q162](questions/q162.md): How many distinct parts are always replaced (part_new=1 in a
- [PASS] [Q163](questions/q163.md): Which parts have the highest ratio of major repairs (part_re
- [PASS] [Q164](questions/q164.md): How many claims have all parts replaced (part_new=1) and no 
- [PASS] [Q165](questions/q165.md): How many opis_rows have quantity greater than 1?

### Supplier

- [PASS] [Q166](questions/q166.md): What are the top 10 suppliers by total expense value (value_
- [PASS] [Q167](questions/q167.md): What are the top 10 suppliers by number of expense lines?
- [PASS] [Q168](questions/q168.md): What is the average expense line value (value_vat) overall?
- [PASS] [Q169](questions/q169.md): What is the expense subtype distribution? Show counts and to
- [PASS] [Q170](questions/q170.md): What share of expense value comes from 'unlinked' expenses (
- [FAIL] [Q171](questions/q171.md): What is the average number of expense lines per MC estimate?
- [PASS] [Q172](questions/q172.md): What are the top 10 most expensive individual expense names 
- [PASS] [Q173](questions/q173.md): What is the expense distribution by expense type name? Join 
- [PASS] [Q174](questions/q174.md): What is the total expense value by unit type? Join with inv_
- [FAIL] [Q175](questions/q175.md): What percentage of total expense value do the top 3 supplier
- [PASS] [Q176](questions/q176.md): How many expense lines have a discount (discount_value > 0)?
- [PASS] [Q177](questions/q177.md): What is the average final_price by expense type (joined with
- [PASS] [Q178](questions/q178.md): What is the total expense value for MC estimates only (not N
- [PASS] [Q179](questions/q179.md): What is the distribution of expense line counts per claim? S
- [PASS] [Q180](questions/q180.md): Which suppliers have the highest average expense line value?
- [PASS] [Q181](questions/q181.md): What is the total value of new parts expenses (expense_subty
- [PASS] [Q182](questions/q182.md): How many expense lines have value_vat greater than 1000?
- [FAIL] [Q183](questions/q183.md): What is the average total expense value per damage line for 
- [PASS] [Q184](questions/q184.md): What is the total expense value by year (based on the estima
- [PASS] [Q185](questions/q185.md): What is the total expense value for paint-related expense ty

### Repair

- [PASS] [Q186](questions/q186.md): What are the top 10 repair shops (service_id) by number of c
- [PASS] [Q187](questions/q187.md): What is the average repair duration in days for the top 5 bu
- [PASS] [Q188](questions/q188.md): What is the distribution of repair statuses?
- [PASS] [Q189](questions/q189.md): How many claims have a repair request vs how many do not?
- [PASS] [Q190](questions/q190.md): What is the average number of days from claim filing (opis_d
- [PASS] [Q191](questions/q191.md): How many repairs have a start date but no end date?
- [PASS] [Q192](questions/q192.md): Which top 5 repair shops have the most completed repairs (re
- [PASS] [Q193](questions/q193.md): What is the overall average repair duration in days (where b
- [PASS] [Q194](questions/q194.md): How many repair claims exist per car make (car_make_name)?
- [PASS] [Q195](questions/q195.md): What is the repair completion rate (repairs with end_repair 
- [PASS] [Q196](questions/q196.md): Which repair shops have the fastest average repair time? Sho
- [PASS] [Q197](questions/q197.md): How many repair requests were sent per year?
- [PASS] [Q198](questions/q198.md): How many repair requests were sent per month?
- [PASS] [Q199](questions/q199.md): Which repair shops handle the most diverse set of car brands
- [PASS] [Q200](questions/q200.md): What is the average number of days from send_date to start_r
- [PASS] [Q201](questions/q201.md): How many claims have multiple repair records?
- [PASS] [Q202](questions/q202.md): How many repairs are still pending (repair_status=0)?
- [PASS] [Q203](questions/q203.md): What are the 5 longest repair durations (in days)?
- [PASS] [Q204](questions/q204.md): How many repair requests were sent per quarter?
- [PASS] [Q205](questions/q205.md): What is the average number of repairs per repair shop?
- [PASS] [Q206](questions/q206.md): How many claims were sent to a repair shop but are still pen
- [PASS] [Q207](questions/q207.md): Which repair shops have a 100% completion rate (all repairs 
- [PASS] [Q208](questions/q208.md): What is the distribution of repair durations in buckets (0-7
- [PASS] [Q209](questions/q209.md): Which repair shops have handled repairs across the most year
- [FAIL] [Q210](questions/q210.md): How many claims have both a repair request and an MC estimat

### MC_vs_N24

- [PASS] [Q211](questions/q211.md): How many claims have both MC and N24 estimates?
- [PASS] [Q212](questions/q212.md): What is the average MC total cost vs average N24 total cost 
- [FAIL] [Q213](questions/q213.md): For claims with both MC and N24, what is the average MC minu
- [FAIL] [Q214](questions/q214.md): How many claims have N24 estimate exceeding MC estimate?
- [FAIL] [Q215](questions/q215.md): How many claims have MC estimate exceeding N24 estimate?
- [FAIL] [Q216](questions/q216.md): What is the average MC/N24 cost ratio for claims that have b
- [PASS] [Q217](questions/q217.md): For claims with both estimates, how does the parts cost comp
- [PASS] [Q218](questions/q218.md): For claims with both estimates, how does the paint cost comp
- [PASS] [Q219](questions/q219.md): For claims with both estimates, how does the repair labor co
- [PASS] [Q220](questions/q220.md): What is the MC vs N24 average cost difference by car brand? 
- [PASS] [Q221](questions/q221.md): What is the MC vs N24 average cost difference by damage type
- [PASS] [Q222](questions/q222.md): How many N24 estimates exist in total?
- [FAIL] [Q223](questions/q223.md): What is the average N24 estimated total cost?
- [PASS] [Q224](questions/q224.md): How many N24 estimates were created per year?
- [PASS] [Q225](questions/q225.md): How many claims have only N24 estimates (no MC)?

### CycleTime

- [PASS] [Q226](questions/q226.md): What is the average number of days from accident (damage_dat
- [PASS] [Q227](questions/q227.md): What is the average number of days from claim filing (opis_d
- [PASS] [Q228](questions/q228.md): What is the average repair duration from start to end in day
- [FAIL] [Q229](questions/q229.md): How many claims were filed on the same day as the damage eve
- [FAIL] [Q230](questions/q230.md): How many claims were filed more than 90 days after the damag
- [PASS] [Q231](questions/q231.md): What is the average number of days from damage event to repa
- [PASS] [Q232](questions/q232.md): How many claims have multiple generated documents (inspectio
- [PASS] [Q233](questions/q233.md): What is the average number of generated documents per claim?
- [PASS] [Q234](questions/q234.md): What is the distribution of estimate revision counts (number
- [FAIL] [Q235](questions/q235.md): How many claims have 3 or more MC estimate revisions?
- [PASS] [Q236](questions/q236.md): What is the average number of days between the damage event 
- [PASS] [Q237](questions/q237.md): What is the distribution of repair durations in days (0-7, 8
- [PASS] [Q238](questions/q238.md): What are the 5 fastest completed repairs (shortest duration 
- [FAIL] [Q239](questions/q239.md): How many repairs have a start_repair date before the claim f
- [PASS] [Q240](questions/q240.md): What is the average filing lag (damage_date to opis_date) by
- [FAIL] [Q241](questions/q241.md): What is the monthly average filing lag trend?
- [FAIL] [Q242](questions/q242.md): How many claims have generated documents but no MC estimate?
- [PASS] [Q243](questions/q243.md): What is the average number of days from repair request (send
- [PASS] [Q244](questions/q244.md): How many repairs were completed before the estimated_date_re
- [PASS] [Q245](questions/q245.md): What is the average total lifecycle duration (from damage_da

### DataQuality

- [PASS] [Q246](questions/q246.md): How many claims (opis) reference a damage_id that does not e
- [PASS] [Q247](questions/q247.md): How many opis_rows reference an opis_id that does not exist 
- [PASS] [Q248](questions/q248.md): How many MC estimates reference an opis_id that does not exi
- [PASS] [Q249](questions/q249.md): How many opis_rows have a part_id outside the known catalog 
- [PASS] [Q250](questions/q250.md): How many opis_rows reference a part_id that has no matching 
- [PASS] [Q251](questions/q251.md): How many MC estimates have negative cost values (total_cost 
- [PASS] [Q252](questions/q252.md): How many claims were filed (opis_date) before the damage eve
- [PASS] [Q253](questions/q253.md): How many repair requests (send_date) were sent before the cl
- [PASS] [Q254](questions/q254.md): Are there any MC estimate records with type not in ('mc', 'n
- [FAIL] [Q255](questions/q255.md): How many opis records reference a car_id that does not exist
- [PASS] [Q256](questions/q256.md): How many opis records reference a damage_id that does not ex
- [PASS] [Q257](questions/q257.md): How many damage events have a future damage_date (after toda
- [PASS] [Q258](questions/q258.md): How many cars have an invalid manufacturing year (before 190
- [PASS] [Q259](questions/q259.md): How many MC estimates have total_cost that differs from the 
- [PASS] [Q260](questions/q260.md): How many expense lines have negative values (value_vat < 0)?
- [PASS] [Q261](questions/q261.md): Are there any duplicate opis_rows (same opis_id and part_id 
- [PASS] [Q262](questions/q262.md): How many claims have opis_date earlier than damage_date by m
- [PASS] [Q263](questions/q263.md): How many repairs have end_repair before start_repair?
- [PASS] [Q264](questions/q264.md): How many MC estimates are inactive (is_active=0)?
- [PASS] [Q265](questions/q265.md): How many expense lines reference a doc_id (invcalc_id) that 

### Geographic

- [PASS] [Q266](questions/q266.md): What is the average damage total_cost by country (damage_pla
- [PASS] [Q267](questions/q267.md): What are the top 10 damage locations by frequency?
- [PASS] [Q268](questions/q268.md): How many claims exist per country (damage_place_country)?
- [PASS] [Q269](questions/q269.md): What is the average MC estimated cost by country?
- [PASS] [Q270](questions/q270.md): How many claims occurred in Sofia vs all other locations?
- [PASS] [Q271](questions/q271.md): What is the damage type distribution by country?
- [PASS] [Q272](questions/q272.md): What is the average filing lag by country?
- [PASS] [Q273](questions/q273.md): What are the top 10 damage locations by total cost?
- [PASS] [Q274](questions/q274.md): What is the average repair duration by damage location? Show
- [PASS] [Q275](questions/q275.md): How many claims have no damage place information (empty or n
- [PASS] [Q276](questions/q276.md): How many distinct damage locations exist in the database?
- [PASS] [Q277](questions/q277.md): Which damage location has the highest average MC estimated c
- [PASS] [Q278](questions/q278.md): What is the geographic distribution of car makes? Show top 5
- [PASS] [Q279](questions/q279.md): How many claims by country were there per year?
- [PASS] [Q280](questions/q280.md): For damage locations with at least 5 claims, what is the ave

### Complex

- [FAIL] [Q281](questions/q281.md): How many claims have an MC estimate above the P90 threshold?
- [FAIL] [Q282](questions/q282.md): How many claims are missing MC estimates entirely?
- [PASS] [Q283](questions/q283.md): Build a claim-level summary: show brand, damage_typeid, dama
- [PASS] [Q284](questions/q284.md): How does vehicle age (year of damage minus car_year) affect 
- [PASS] [Q285](questions/q285.md): Show frequency-severity decomposition by brand: claim count 
- [PASS] [Q286](questions/q286.md): Show claim count by claim_type and whether an MC estimate ex
- [PASS] [Q287](questions/q287.md): What is the average MC estimated cost for claims with major 
- [PASS] [Q288](questions/q288.md): What is the parts share vs paint share by brand from MC esti
- [PASS] [Q289](questions/q289.md): Which claims have unusually high labor hours per damage line
- [PASS] [Q290](questions/q290.md): What is the claim count cross-tabulation by brand and damage
- [FAIL] [Q291](questions/q291.md): What is the ratio of MC estimated cost to damage total_cost?
- [PASS] [Q292](questions/q292.md): What are the top 5 car models (car_mc_modelname resolved via
- [PASS] [Q293](questions/q293.md): What is the average MC estimated cost by repair severity (ba
- [FAIL] [Q294](questions/q294.md): How many claims have both generated documents (inspections) 
- [PASS] [Q295](questions/q295.md): What is the average number of damage lines by car year group
- [PASS] [Q296](questions/q296.md): What is the MC estimated cost per damage line by brand?
- [PASS] [Q297](questions/q297.md): For claims with both repairs and MC estimates, what is the a
- [PASS] [Q298](questions/q298.md): What is the supplier diversity (distinct supplier count) per
- [PASS] [Q299](questions/q299.md): What is the average MC estimated cost by filing lag bucket (
- [PASS] [Q300](questions/q300.md): Build a brand-level summary: brand name, total claims, avera
