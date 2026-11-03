-- EBAN: purchase requisition items
select
    BANFN                                   as requisition_id,
    BNFPO                                   as requisition_item,
    EBELN || EBELP                          as case_key,
    {{ sap_timestamp('BADAT', 'ZZ_ERZET') }} as created_at,
    ERNAM                                   as created_by,
    cast(RLWRT as double)                   as value_eur,
    cast(ZZ_EVENT_SEQ as integer)           as event_seq
from {{ source('sap', 'EBAN') }}
