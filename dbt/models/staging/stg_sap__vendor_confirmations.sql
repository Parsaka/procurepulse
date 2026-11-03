-- EKES: order confirmations (EBTYP 'AB'); ZZ_CONF_KIND 1 = received, 2 = updated
select
    EBELN || EBELP                          as case_key,
    cast(ETENS as integer)                  as confirmation_seq,
    EBTYP                                   as confirmation_category,
    case ZZ_CONF_KIND when '1' then 'received' when '2' then 'updated' end as confirmation_kind,
    {{ sap_timestamp('ERDAT', 'EZEIT') }}   as created_at,
    ERNAM                                   as created_by,
    cast(ETENS as integer)                  as event_seq
from {{ source('sap', 'EKES') }}
