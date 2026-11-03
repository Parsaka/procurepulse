-- How often each deviation type occurs, and how much value it touches (mature cohort)
{% set rules = [
    ('dev_invoice_before_gr', 'Invoice posted before goods receipt', '3-way match, invoice after GR'),
    ('dev_paid_before_gr', 'Invoice paid before goods receipt', '3-way match, invoice before GR'),
    ('dev_gr_on_two_way_item', 'Goods receipt on a 2-way item', '2-way match'),
    ('dev_invoice_on_consignment', 'Invoice on a consignment item', 'Consignment'),
    ('dev_po_after_invoice', 'Purchase order created after the invoice date', 'All'),
    ('dev_price_change_after_invoice', 'Price changed after invoice receipt', 'All'),
    ('dev_quantity_change_after_gr', 'Quantity changed after goods receipt', 'All'),
    ('dev_payment_block', 'Invoice blocked for payment (variance)', 'All'),
    ('dev_reversal', 'Goods receipt or invoice reversed', 'All'),
] %}
with base as (
    select * from {{ ref('fct_po_item') }} where is_mature_cohort
)
{% for col, label, scope in rules %}
select
    '{{ col }}'                                                         as deviation_code,
    '{{ label }}'                                                       as deviation_label,
    '{{ scope }}'                                                       as applies_to,
    count(case when {{ col }} then 1 end)                               as po_items,
    count(case when {{ col }} then 1 end) * 1.0 / count(*)              as share_of_items,
    sum(case when {{ col }} then net_value_eur else 0 end)              as po_value_eur,
    sum(case when {{ col }} then net_value_eur else 0 end) / nullif(sum(net_value_eur), 0) as share_of_value
from base
{% if not loop.last %}union all{% endif %}
{% endfor %}
