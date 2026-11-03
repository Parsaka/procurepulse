"""Export the small, aggregated tables the Streamlit app and Power BI read.

The app runs on Streamlit Community Cloud straight from the repository, so it
ships only aggregates (a few MB). Case-level data never leaves the warehouse,
except the top-decile alert list, which is what a buyer would act on.
"""
from __future__ import annotations

import json
import shutil

from analytics.common import OUT_DIR, ROOT, connect

APP_DATA = ROOT / "app" / "data"

TABLES = {
    "monthly_kpis": "select * from marts.mart_p2p_monthly_kpis order by po_created_month, item_category",
    "deviation_summary": "select * from marts.mart_deviation_summary order by po_items desc",
    "vendor_scorecard": "select * from marts.mart_vendor_scorecard order by deviation_volume_rank",
    "process_variants": """
        select * from marts.mart_process_variants
        qualify row_number() over (partition by item_category order by po_items desc) <= 25
        order by item_category, po_items desc""",
    "handover_times": """
        select * from marts.mart_handover_times
        qualify row_number() over (partition by item_category order by total_wait_days desc) <= 15
        order by item_category, total_wait_days desc""",
    "conformance_summary": "select * from analytics.conformance_summary",
    "deviation_effects": "select * from analytics.deviation_effects",
    "intervention_value": "select * from analytics.intervention_value",
    "model_metrics": "select * from analytics.model_metrics",
    "model_calibration": "select * from analytics.model_calibration order by risk_decile",
    "risk_drivers": "select * from analytics.risk_drivers order by mean_abs_shap desc",
    "early_warning_alerts": "select * exclude (label) from analytics.early_warning_alerts order by risk_score desc",
    "vendor_concentration": """
        with v as (
            select vendor_id, count(*) filter (where has_rework) as rework_items
            from (select vendor_id, (dev_price_change_after_invoice or dev_quantity_change_after_gr
                                     or dev_payment_block or dev_reversal) as has_rework
                  from marts.fct_po_item where is_in_scope)
            group by 1)
        select row_number() over (order by rework_items desc, vendor_id) as vendor_rank,
               count(*) over () as vendors,
               rework_items,
               sum(rework_items) over (order by rework_items desc, vendor_id) / sum(rework_items) over () as cum_share
        from v order by vendor_rank""",
    # monthly rework rate of the 10 vendors with the most rework items: a simple control chart
    "vendor_monthly_rework": """
        with base as (
            select vendor_id, date_trunc('month', po_created_at) as po_created_month,
                   (dev_price_change_after_invoice or dev_quantity_change_after_gr
                    or dev_payment_block or dev_reversal) as has_rework
            from marts.fct_po_item where is_in_scope),
        top as (select vendor_id from base group by 1 order by count(*) filter (where has_rework) desc limit 10)
        select vendor_id, po_created_month, count(*) as po_items, avg(has_rework::int) as rework_rate
        from base join top using (vendor_id) group by 1, 2 order by 1, 2""",
}
JSONS = ["conformance_overall.json", "cost_of_deviation.json", "early_warning.json"]


def main() -> None:
    con = connect(read_only=True)
    APP_DATA.mkdir(parents=True, exist_ok=True)
    for name, sql in TABLES.items():
        df = con.execute(sql).fetchdf()
        df.to_parquet(APP_DATA / f"{name}.parquet", index=False)
        print(f"{name:<22} {len(df):>7,} rows")
    for j in JSONS:
        shutil.copy(OUT_DIR / j, APP_DATA / j)
    meta = con.execute("""
        select min(po_created_at)::date, max(po_created_at)::date, count(*), count(distinct vendor_id)
        from marts.fct_po_item where is_in_scope""").fetchone()
    (APP_DATA / "dataset.json").write_text(json.dumps(
        {"first_po": str(meta[0]), "last_po": str(meta[1]), "po_items_in_scope": meta[2], "vendors": meta[3]},
        indent=2))


if __name__ == "__main__":
    main()
