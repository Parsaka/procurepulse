-- EKBE (VGABE 1): goods receipts; movement type 101 = receipt, 102 = reversal
select
    BELNR                                   as material_document_id,
    GJAHR                                   as fiscal_year,
    EBELN || EBELP                          as case_key,
    BWART                                   as movement_type,
    SHKZG = 'H'                             as is_reversal,
    {{ sap_timestamp('CPUDT', 'CPUTM') }}   as posted_at,
    cast(DMBTR as double)                   as amount_eur,
    ERNAM                                   as created_by,
    cast(ZZ_EVENT_SEQ as integer)           as event_seq
from {{ source('sap', 'EKBE') }}
where VGABE = '1'
