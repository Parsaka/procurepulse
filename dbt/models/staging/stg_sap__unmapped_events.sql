select
    EBELN || EBELP                          as case_key,
    ACTIVITY                                as activity,
    {{ sap_timestamp('UDATE', 'UTIME') }}   as event_at,
    USNAM                                   as created_by,
    cast(NETWR as double)                   as amount_eur,
    cast(ZZ_EVENT_SEQ as integer)           as event_seq
from {{ source('sap', 'ZZ_UNMAPPED_EVENTS') }}
