-- The event log rebuilt from SAP tables must reproduce the source log exactly:
-- same activities, same number of events and cases per activity.
with rebuilt as (
    select activity, count(*) as events, count(distinct case_key) as cases
    from {{ ref('int_p2p__events') }} group by activity
),
audit as (
    select ACTIVITY as activity, cast(EVENTS as bigint) as events, cast(CASES as bigint) as cases
    from {{ source('sap', 'ZZ_AUDIT_EVENT_COUNTS') }}
)
select coalesce(a.activity, r.activity) as activity, a.events as source_events, r.events as rebuilt_events,
       a.cases as source_cases, r.cases as rebuilt_cases
from audit a
full outer join rebuilt r on r.activity = a.activity
where a.activity is null or r.activity is null or a.events <> r.events or a.cases <> r.cases
