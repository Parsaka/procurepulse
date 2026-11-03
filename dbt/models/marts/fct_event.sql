-- Event grain fact: one row per SAP-derived process event
select
    e.event_id,
    e.case_key,
    e.activity,
    a.stage,
    a.stage_order,
    coalesce(a.is_rework, false)                                   as is_rework,
    e.event_at,
    cast(e.event_at as date)                                       as event_date,
    e.user_name,
    case when e.user_name is null then 'Unknown / external'
         when e.is_batch_user    then 'Batch job'
         else 'Human user' end                                     as actor_type,
    (e.user_name is not null and not e.is_batch_user)              as is_manual_touch,
    e.amount_eur,
    e.source_table,
    e.event_seq,
    e.is_outside_window
from {{ ref('int_p2p__events') }} e
left join {{ ref('dim_activity') }} a on a.activity = e.activity
