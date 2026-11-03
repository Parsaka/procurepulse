-- Vendor scorecard over the mature cohort (90+ days observed); vendors with at least 20 items
with v as (
    select
        p.vendor_id,
        count(*)                                                    as po_items,
        sum(p.net_value_eur)                                        as po_value_eur,
        avg(case when p.has_deviation then 1.0 else 0.0 end)        as deviation_rate,
        avg(p.n_manual_rework_touches)                              as avg_rework_touches,
        avg(case when p.dev_payment_block then 1.0 else 0.0 end)    as payment_block_rate,
        avg(case when p.dev_po_after_invoice then 1.0 else 0.0 end) as po_after_invoice_rate,
        {{ median('p.cycle_days') }}                                as median_cycle_days
    from {{ ref('fct_po_item') }} p
    where p.is_mature_cohort
    group by p.vendor_id
    having count(*) >= 20
)
select
    v.*,
    d.vendor_name,
    d.vendor_size_band,
    rank() over (order by v.deviation_rate * v.po_items desc)        as deviation_volume_rank
from v
join {{ ref('dim_vendor') }} d on d.vendor_id = v.vendor_id
