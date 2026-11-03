-- Users who touched the process. BATCH* users are background jobs (automation).
select
    user_name,
    case when user_name like 'BATCH%' then 'Batch job' else 'Human user' end as user_type,
    count(*)                       as events,
    count(distinct case_key)       as po_items
from {{ ref('int_p2p__events') }}
where user_name is not null
group by user_name
