-- BSAK: cleared vendor items; AUGDT = clearing (payment) date
select
    AUGBL                                   as clearing_document_id,
    GJAHR                                   as fiscal_year,
    EBELN || EBELP                          as case_key,
    {{ sap_timestamp('AUGDT', 'ZZ_CPUTM') }} as cleared_at,
    cast(DMBTR as double)                   as amount_eur,
    USNAM                                   as created_by,
    cast(ZZ_EVENT_SEQ as integer)           as event_seq
from {{ source('sap', 'BSAK') }}
