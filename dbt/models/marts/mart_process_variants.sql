-- Process variants: the ordered activity sequence of each in-scope PO item
with seq as (
    select
        e.case_key,
        {{ ordered_listagg('e.activity', 'e.event_at, e.event_seq') }} as variant
    from {{ ref('fct_event') }} e
    join {{ ref('fct_po_item') }} p on p.case_key = e.case_key and p.is_in_scope
    group by e.case_key
)
select
    {{ md5_hash('s.variant') }}                                  as variant_id,
    s.variant,
    p.item_category,
    count(*)                                                     as po_items,
    sum(p.net_value_eur)                                         as po_value_eur,
    avg(case when p.has_deviation then 1.0 else 0.0 end)         as deviation_rate,
    {{ median('p.cycle_days') }}                                 as median_cycle_days,
    avg(p.n_manual_touches)                                      as avg_manual_touches
from seq s
join {{ ref('fct_po_item') }} p on p.case_key = s.case_key
group by s.variant, p.item_category
