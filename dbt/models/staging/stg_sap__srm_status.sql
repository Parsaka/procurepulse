-- SAP SRM status history of shopping carts / POs created in SRM
select
    EBELN || EBELP                          as case_key,
    STATUS_TEXT                             as status_text,
    {{ sap_timestamp('UDATE', 'UTIME') }}   as changed_at,
    USNAM                                   as changed_by,
    cast(ZZ_EVENT_SEQ as integer)           as event_seq
from {{ source('sap', 'SRM_STATUS') }}
