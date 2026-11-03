// Power Query (M): one query per table. Home > Transform data > New source > Blank query,
// open Advanced editor, paste one block, and name the query after the table.
// First create a text parameter "DataFolder" (Manage parameters) pointing at <repo>\data\bi\

// fct_po_item
let
    Source = Parquet.Document(File.Contents(DataFolder & "fct_po_item.parquet")),
    Typed = Table.TransformColumnTypes(Source, {
        {"net_value_eur", type number}, {"cycle_days", type number}, {"e2e_cycle_days", type number},
        {"invoice_to_clear_days", type number}, {"po_created_month", type date}})
in
    Typed

// The other tables need no typing; repeat this pattern with their file names:
// fct_event, dim_vendor, dim_date, dim_activity, dim_user, dim_material_group,
// dim_company_code, deviation_effects, intervention_value, early_warning_scores
let
    Source = Parquet.Document(File.Contents(DataFolder & "dim_vendor.parquet"))
in
    Source

// Snowflake path instead of files (after `make snowflake`):
// Get data > Snowflake, server <account>.snowflakecomputing.com, warehouse PP_WH,
// role PP_REPORTER, then pick PROCUREPULSE.MARTS.* and PROCUREPULSE.ANALYTICS.*.
