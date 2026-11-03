-- Directly-follows relations with waiting time: where does the process wait?
with ordered as (
    select
        e.case_key, e.activity, e.event_at, p.item_category,
        lead(e.activity) over (partition by e.case_key order by e.event_at, e.event_seq) as next_activity,
        lead(e.event_at) over (partition by e.case_key order by e.event_at, e.event_seq) as next_event_at
    from {{ ref('fct_event') }} e
    join {{ ref('fct_po_item') }} p on p.case_key = e.case_key and p.is_in_scope
)
select
    item_category,
    activity                                                  as from_activity,
    next_activity                                             as to_activity,
    count(*)                                                  as transitions,
    {{ median(days_between('event_at', 'next_event_at')) }}   as median_wait_days,
    {{ percentile(days_between('event_at', 'next_event_at'), 0.9) }} as p90_wait_days,
    sum({{ days_between('event_at', 'next_event_at') }})      as total_wait_days
from ordered
where next_activity is not null
group by item_category, activity, next_activity
