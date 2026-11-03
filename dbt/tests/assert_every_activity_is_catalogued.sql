-- Every activity must have a stage and rework flag in the activity catalog
select distinct e.activity
from {{ ref('int_p2p__events') }} e
left join {{ ref('activity_catalog') }} a on a.activity = e.activity
where a.activity is null
