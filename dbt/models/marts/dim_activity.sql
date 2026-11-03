select
    activity,
    stage,
    stage_order,
    is_rework,
    sap_object,
    description
from {{ ref('activity_catalog') }}
