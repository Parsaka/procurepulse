select
    LIFNR                                   as vendor_id,
    {{ sap_alpha_out('LIFNR') }}            as vendor_number,
    NAME1                                   as vendor_name,
    LAND1                                   as country
from {{ source('sap', 'LFA1') }}
