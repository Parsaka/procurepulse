select case_key from {{ ref('fct_po_item') }}
where has_deviation <> (n_deviation_types > 0)
