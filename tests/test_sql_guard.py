import pytest

from copilot.tools import UnsafeQuery, check_sql

ALLOWED = [
    "select count(*) from marts.fct_po_item where is_in_scope",
    "with v as (select vendor_id, count(*) n from marts.fct_po_item group by 1) select * from v order by n desc",
    "select a.excess from analytics.deviation_effects a join analytics.intervention_value i on true limit 1",
    "select 1 from marts.dim_date union all select 2 from marts.dim_date",
]
REJECTED = [
    "drop table marts.fct_po_item",
    "delete from marts.fct_po_item",
    "insert into marts.dim_date select * from marts.dim_date",
    "update marts.dim_vendor set vendor_name = 'x'",
    "create table marts.x as select 1",
    "copy marts.fct_po_item to '/tmp/out.csv'",
    "select 1; drop table marts.fct_po_item",
    "select * from read_csv('/etc/passwd')",
    "select * from read_parquet('data/landing/sap/EKKO/**/*.parquet')",
    "select * from information_schema.tables",
    "select * from staging.stg_sap__vendors",
    "select * from fct_po_item",
    "attach 'x.duckdb' as x",
    "pragma database_list",
]


@pytest.mark.parametrize("sql", ALLOWED)
def test_allows_read_only_selects(sql):
    assert check_sql(sql) == sql


@pytest.mark.parametrize("sql", REJECTED)
def test_rejects_everything_else(sql):
    with pytest.raises(UnsafeQuery):
        check_sql(sql)
