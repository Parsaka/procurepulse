"""Export the star schema for Power BI Desktop (import mode) to data/bi/*.parquet.

Power BI reads these with its Parquet connector (see bi/powerbi/README.md). On the
Snowflake path, Power BI connects to PROCUREPULSE.MARTS directly instead.
"""
from __future__ import annotations

from analytics.common import ROOT, connect

OUT = ROOT / "data" / "bi"
TABLES = {
    "fct_po_item": "select * exclude (case_label) from marts.fct_po_item where is_in_scope",
    "fct_event": """select e.event_id, e.case_key, e.activity, e.event_at, e.event_date, e.user_name,
                           e.actor_type, e.is_manual_touch, e.is_rework, e.amount_eur, e.event_seq
                    from marts.fct_event e join marts.fct_po_item p using (case_key) where p.is_in_scope""",
    "dim_vendor": "select * from marts.dim_vendor",
    "dim_date": "select * from marts.dim_date",
    "dim_activity": "select * from marts.dim_activity",
    "dim_user": "select * from marts.dim_user",
    "dim_material_group": "select * from marts.dim_material_group",
    "dim_company_code": "select * from marts.dim_company_code",
    "deviation_effects": "select * from analytics.deviation_effects",
    "intervention_value": "select * from analytics.intervention_value",
    "early_warning_scores": "select * from analytics.early_warning_scores",
}


def main() -> None:
    con = connect(read_only=True)
    OUT.mkdir(parents=True, exist_ok=True)
    for name, sql in TABLES.items():
        con.execute(f"copy ({sql}) to '{(OUT / f'{name}.parquet').as_posix()}' (format parquet, compression snappy)")
        print(f"{name:<22} {con.execute(f'select count(*) from ({sql})').fetchone()[0]:>10,} rows")


if __name__ == "__main__":
    main()
