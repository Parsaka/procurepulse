select case_key, count(*) as creations
from {{ ref('fct_event') }}
where activity = 'Create Purchase Order Item'
group by case_key
having count(*) <> 1
