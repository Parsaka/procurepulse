select case_key, cycle_days, invoice_to_clear_days, po_to_gr_days
from {{ ref('fct_po_item') }}
where is_in_scope and (cycle_days < 0 or po_to_gr_days < -1)
