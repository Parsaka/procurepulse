-- EDIDC: inbound IDocs from vendors. INVOIC01 = invoice, INVOIC02 = debit memo (this extract's convention)
select
    DOCNUM                                  as idoc_number,
    MESTYP                                  as message_type,
    IDOCTP                                  as idoc_type,
    ZZ_EBELN || ZZ_EBELP                    as case_key,
    {{ sap_timestamp('CREDAT', 'CRETIM') }} as created_at,
    cast(ZZ_AMOUNT as double)               as amount_eur,
    cast(ZZ_EVENT_SEQ as integer)           as event_seq
from {{ source('sap', 'EDIDC') }}
where DIRECT = '2'
