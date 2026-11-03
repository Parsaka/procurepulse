-- Case grain fact: one row per PO item with milestones, effort and rule-based deviations.
-- Deviation rules compare each item with the target flow of its item category
-- (docs/kpi_definitions.md explains every rule).
{% set obs_days = 90 %}

with ev as (
    select * from {{ ref('fct_event') }}
),

agg as (
    select
        case_key,
        count(*)                                                                    as n_events,
        count(case when is_manual_touch then 1 end)                                 as n_manual_touches,
        count(case when is_rework then 1 end)                                       as n_rework_events,
        count(case when is_rework and is_manual_touch then 1 end)                   as n_manual_rework_touches,
        count(case when actor_type = 'Batch job' then 1 end)                        as n_batch_events,
        count(case when is_outside_window then 1 end)                               as n_events_outside_window,
        min(event_at)                                                               as first_event_at,
        max(event_at)                                                               as last_event_at,
        min(case when activity = 'Create Purchase Order Item'   then event_at end) as po_created_at,
        min(case when activity = 'Create Purchase Requisition Item' then event_at end) as pr_created_at,
        min(case when activity = 'Record Goods Receipt'         then event_at end) as first_gr_at,
        max(case when activity = 'Record Goods Receipt'         then event_at end) as last_gr_at,
        min(case when activity = 'Record Service Entry Sheet'   then event_at end) as first_ses_at,
        min(case when activity = 'Vendor creates invoice'       then event_at end) as first_vendor_invoice_at,
        min(case when activity = 'Record Invoice Receipt'       then event_at end) as first_ir_at,
        min(case when activity = 'Clear Invoice'                then event_at end) as first_clear_at,
        max(case when activity = 'Clear Invoice'                then event_at end) as last_clear_at,
        count(case when activity = 'Record Goods Receipt'       then 1 end)        as n_goods_receipts,
        count(case when activity = 'Record Invoice Receipt'     then 1 end)        as n_invoices,
        count(case when activity = 'Clear Invoice'              then 1 end)        as n_clearings,
        count(case when activity = 'Change Price'               then 1 end)        as n_price_changes,
        count(case when activity = 'Change Quantity'            then 1 end)        as n_quantity_changes,
        count(case when activity in ('Set Payment Block', 'Remove Payment Block') then 1 end) as n_payment_block_events,
        count(case when activity in ('Cancel Goods Receipt', 'Cancel Invoice Receipt', 'Cancel Subsequent Invoice') then 1 end) as n_reversals,
        count(case when activity in ('Delete Purchase Order Item', 'Block Purchase Order Item') then 1 end) as n_delete_or_block
    from ev
    group by case_key
),

ordered_changes as (
    -- changes that happen after a milestone (needs the milestone per case)
    select
        e.case_key,
        count(case when e.activity = 'Change Price' and e.event_at > a.first_ir_at then 1 end)    as n_price_changes_after_invoice,
        count(case when e.activity = 'Change Quantity' and e.event_at > a.first_gr_at then 1 end) as n_quantity_changes_after_gr
    from ev e
    join agg a on a.case_key = e.case_key
    where e.activity in ('Change Price', 'Change Quantity')
    group by e.case_key
),

log_bounds as (
    select max(event_at) as log_end_at from ev where not is_outside_window
),

base as (
    select
        c.*,
        a.n_events, a.n_manual_touches, a.n_rework_events, a.n_manual_rework_touches, a.n_batch_events,
        a.n_events_outside_window, a.first_event_at, a.last_event_at, a.po_created_at, a.pr_created_at,
        a.first_gr_at, a.last_gr_at, a.first_ses_at, a.first_vendor_invoice_at, a.first_ir_at,
        a.first_clear_at, a.last_clear_at, a.n_goods_receipts, a.n_invoices, a.n_clearings,
        a.n_price_changes, a.n_quantity_changes, a.n_payment_block_events, a.n_reversals, a.n_delete_or_block,
        coalesce(o.n_price_changes_after_invoice, 0) as n_price_changes_after_invoice,
        coalesce(o.n_quantity_changes_after_gr, 0)   as n_quantity_changes_after_gr,
        b.log_end_at
    from {{ ref('int_p2p__cases') }} c
    join agg a on a.case_key = c.case_key
    left join ordered_changes o on o.case_key = c.case_key
    cross join log_bounds b
),

flags as (
    select
        *,
        -- target-flow deviations per item category
        (item_category = '3-way match, invoice after GR'
            and n_invoices > 0 and (first_gr_at is null or first_ir_at < first_gr_at))     as dev_invoice_before_gr,
        (item_category = '3-way match, invoice before GR'
            and n_clearings > 0 and (first_gr_at is null or first_clear_at < first_gr_at)) as dev_paid_before_gr,
        (item_category = '2-way match' and n_goods_receipts > 0)                             as dev_gr_on_two_way_item,
        (item_category = 'Consignment' and n_invoices > 0)                                   as dev_invoice_on_consignment,
        -- cross-category deviations
        (first_vendor_invoice_at is not null
            and cast(first_vendor_invoice_at as date) < cast(po_created_at as date))         as dev_po_after_invoice,
        (n_price_changes_after_invoice > 0)                                                  as dev_price_change_after_invoice,
        (n_quantity_changes_after_gr > 0)                                                    as dev_quantity_change_after_gr,
        -- a block on an invoice posted before the GR is the designed control of this category,
        -- so only blocks for other reasons (price / quantity variances) count as deviation
        (n_payment_block_events > 0
            and not (item_category = '3-way match, invoice before GR'
                     and first_ir_at is not null
                     and (first_gr_at is null or first_ir_at < first_gr_at)))                as dev_payment_block,
        (n_reversals > 0)                                                                    as dev_reversal,
        -- end of the case: payment for invoiced flows, last GR for consignment
        case when item_category = 'Consignment' then last_gr_at else last_clear_at end      as case_end_at
    from base
)

select
    *,
    (dev_invoice_before_gr or dev_paid_before_gr or dev_gr_on_two_way_item or dev_invoice_on_consignment
        or dev_po_after_invoice or dev_price_change_after_invoice or dev_quantity_change_after_gr
        or dev_payment_block or dev_reversal)                                               as has_deviation,
    (case when dev_invoice_before_gr then 1 else 0 end + case when dev_paid_before_gr then 1 else 0 end
        + case when dev_gr_on_two_way_item then 1 else 0 end + case when dev_invoice_on_consignment then 1 else 0 end
        + case when dev_po_after_invoice then 1 else 0 end + case when dev_price_change_after_invoice then 1 else 0 end
        + case when dev_quantity_change_after_gr then 1 else 0 end + case when dev_payment_block then 1 else 0 end
        + case when dev_reversal then 1 else 0 end)                                         as n_deviation_types,
    case_end_at is not null                                                                 as is_closed,
    {{ days_between('po_created_at', 'case_end_at') }}                                      as cycle_days,
    -- end-to-end: from the first trace of the need (requisition, PO or a vendor invoice that predates the PO)
    {{ days_between('first_event_at', 'case_end_at') }}                                     as e2e_cycle_days,
    {{ days_between('first_ir_at', 'first_clear_at') }}                                     as invoice_to_clear_days,
    {{ days_between('po_created_at', 'first_gr_at') }}                                      as po_to_gr_days,
    {{ month_start('po_created_at') }}                                                      as po_created_month,
    -- analysis population: clean timestamps, created inside the window
    (n_events_outside_window = 0
        and po_created_at >= cast('{{ var("window_start") }}' as timestamp))                as is_in_scope,
    -- cohort with at least {{ obs_days }} days of observation (avoids right-censoring bias)
    (n_events_outside_window = 0
        and po_created_at >= cast('{{ var("window_start") }}' as timestamp)
        and {{ dbt.dateadd('day', obs_days, 'po_created_at') }} <= log_end_at)              as is_mature_cohort
from flags
