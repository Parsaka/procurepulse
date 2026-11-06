# Power BI report: "P2P Process Cockpit"

The report is code. `build_pbip.py` writes a Power BI Project (`ProcurePulse/ProcurePulse.pbip`): a TMDL
semantic model (11 tables from `data/bi`, 8 relationships, 28 measures, a touch-cost parameter) and a PBIR
report with five pages. Column types come from the Parquet schemas and the measures are the ones in
`measures.dax`, so the report and the dbt KPIs cannot drift apart.

```bash
make bi                                            # or download the powerbi-data artifact from CI
python bi/powerbi/build_pbip.py --data-folder C:\path\to\procurepulse\data\bi\
```

Open `ProcurePulse/ProcurePulse.pbip` in Power BI Desktop (free, Windows), press **Refresh**, then
**File > Save as > Power BI file (*.pbix)**. The `.pbix` is a build output and is not committed.

Notes: the measures table is called `KPIs` because Desktop rejects a table named `Measures`; `data/bi` holds
in-scope items only (251,463 PO items, 1,587,802 events), so its counts are slightly below the full log in
`docs/findings.md`; rework items on the Answer page count the whole log, the per-year figures in the README
are annualised.

The sections below describe the same model for building it by hand.

## 1. Data

```bash
make bi            # writes data/bi/*.parquet (star schema, about 90 MB)
```

In Power BI: **Manage parameters > New**: `DataFolder` (Text) = full path to `data\bi\` with the trailing
backslash. Then add one blank query per table from `power_query.m`.

Alternative: connect to Snowflake (`PROCUREPULSE.MARTS`, role `PP_REPORTER`) in Import mode.

## 2. Model (Model view)

| From (many) | To (one) | Column | Direction |
|---|---|---|---|
| fct_po_item | dim_vendor | vendor_id | single |
| fct_po_item | dim_material_group | material_group | single |
| fct_po_item | dim_company_code | company_code | single |
| fct_po_item | dim_date | po_created_month → date_day *(use `po_created_month`, it is a date)* | single |
| fct_event | fct_po_item | case_key | single |
| fct_event | dim_activity | activity | single |
| fct_event | dim_user | user_name | single |
| early_warning_scores | fct_po_item | case_key | single |

Mark `dim_date` as date table (`date_day`). Hide all keys and the raw `dev_*` columns from report view.
`deviation_effects` and `intervention_value` stay disconnected (they are results tables).

## 3. Measures

Create a table `Measures = {BLANK()}` and paste the blocks from `measures.dax`.
Create the what-if parameter **Touch Cost** (5 to 30, default 15) before the cost measures.

## 4. Pages

1. **Answer**: cards for Conformance Rate, Rework Items, Cost of Rework EUR per Year (with the Touch Cost
   slicer), Control Gap Exposure; a bar chart of `intervention_value[intervention]` by
   Intervention Value EUR per Year (filter `family = rework`).
2. **Process**: matrix of `fct_event` handovers is heavy in DAX; instead use a line chart of Conformance
   Rate and First Time Right Rate by `dim_date[month_start]`, small multiples by item category, and a
   bar chart of Payment Block Rate by spend area.
3. **Deviation cost**: table of `deviation_effects` (excess, ci_low, ci_high, p_value) filtered to
   `outcome = n_manual_touches`, and a second visual for `cycle_days` (never put both on one axis).
4. **Vendors**: table of `dim_vendor` with Rework Items, Rework Rate, Payment Block Rate, Share of Rework
   Items, sorted by Rework Items; line chart of Rework Rate by month with a vendor slicer (control chart).
5. **Early warning**: column chart of Observed Rework Rate (Scored) by `risk_decile`, card Top Decile Lift,
   table of the top-decile items with `top_reason`.

Colours: use one hue (blue `#2a78d6`) for magnitude, grey `#8a8984` for context, and the same order for item
categories everywhere: 3-way before GR blue, 3-way after GR orange `#eb6834`, consignment aqua `#1baf7a`,
2-way yellow `#eda100`.

## 5. Check

Card values must match `docs/findings.md`: Conformance Rate (in scope, all items) equals
`mart_p2p_monthly_kpis` weighted by `po_items`, Top Decile Lift equals the monthly-refit lift in
`data/analytics/early_warning.json`.

Save as `bi/powerbi/ProcurePulse.pbix` and add a screenshot to `docs/img/powerbi_*.png`.
