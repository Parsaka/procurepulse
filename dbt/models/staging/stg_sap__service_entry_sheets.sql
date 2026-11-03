-- ESSR: service entry sheets (acceptance of services instead of a goods receipt)
select
    LBLNI                                   as service_entry_sheet_id,
    EBELN || EBELP                          as case_key,
    {{ sap_timestamp('ERDAT', 'ERZET') }}   as created_at,
    ERNAM                                   as created_by,
    cast(NETWR as double)                   as amount_eur,
    cast(ZZ_EVENT_SEQ as integer)           as event_seq
from {{ source('sap', 'ESSR') }}
