-- Monthly P2P cockpit: PO items by creation month and item category (in-scope items only)
select
    po_created_month,
    item_category,
    count(*)                                                           as po_items,
    sum(net_value_eur)                                                 as po_value_eur,
    avg(case when has_deviation then 0.0 else 1.0 end)                 as conformance_rate,
    sum(case when has_deviation then net_value_eur else 0 end)
        / nullif(sum(net_value_eur), 0)                                as deviating_value_share,
    avg(case when n_manual_rework_touches = 0 then 1.0 else 0.0 end)   as first_time_right_rate,
    avg(n_manual_touches)                                              as avg_manual_touches,
    avg(case when dev_po_after_invoice then 1.0 else 0.0 end)          as po_after_invoice_rate,
    avg(case when is_closed then 1.0 else 0.0 end)                     as closed_rate,
    {{ median('cycle_days') }}                                         as median_cycle_days,
    {{ median('invoice_to_clear_days') }}                              as median_invoice_to_clear_days,
    sum(n_batch_events) * 1.0 / nullif(sum(n_events), 0)               as automation_rate
from {{ ref('fct_po_item') }}
where is_in_scope
group by po_created_month, item_category
