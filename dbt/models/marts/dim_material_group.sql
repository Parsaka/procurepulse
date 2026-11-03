select material_group, spend_area, sub_spend_area, spend_classification
from {{ ref('stg_sap__material_groups') }}
