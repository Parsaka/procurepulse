with items as (
    select vendor_id, count(*) as po_items, sum(net_value_eur) as spend_eur
    from {{ ref('int_p2p__cases') }} group by vendor_id
)
select
    v.vendor_id,
    v.vendor_number,
    v.vendor_name,
    v.country,
    coalesce(i.po_items, 0)     as po_items,
    coalesce(i.spend_eur, 0)    as spend_eur,
    case when coalesce(i.po_items, 0) >= 1000 then 'Large (1000+ items)'
         when coalesce(i.po_items, 0) >= 100  then 'Medium (100-999 items)'
         else 'Small (<100 items)' end as vendor_size_band
from {{ ref('stg_sap__vendors') }} v
left join items i on i.vendor_id = v.vendor_id
