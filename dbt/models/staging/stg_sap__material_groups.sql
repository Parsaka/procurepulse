select
    MATKL                                   as material_group,
    WGBEZ                                   as sub_spend_area,
    ZZ_SPEND_AREA                           as spend_area,
    ZZ_SPEND_CLASS                          as spend_classification
from {{ source('sap', 'T023T') }}
where SPRAS = 'E'
