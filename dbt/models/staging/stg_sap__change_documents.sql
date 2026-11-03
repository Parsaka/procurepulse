-- CDHDR + CDPOS: one row per changed field
select
    h.CHANGENR                              as change_number,
    h.OBJECTCLAS                            as object_class,
    h.OBJECTID || h.ZZ_EBELP                as case_key,
    p.TABNAME                               as table_name,
    p.FNAME                                 as field_name,
    p.CHNGIND                               as change_indicator,
    nullif(p.VALUE_OLD, '')                 as value_old,
    p.VALUE_NEW                             as value_new,
    {{ sap_timestamp('h.UDATE', 'h.UTIME') }} as changed_at,
    h.USERNAME                              as changed_by,
    h.TCODE                                 as transaction_code,
    cast(h.ZZ_EVENT_SEQ as integer)         as event_seq
from {{ source('sap', 'CDHDR') }} h
join {{ source('sap', 'CDPOS') }} p
  on p.OBJECTCLAS = h.OBJECTCLAS and p.OBJECTID = h.OBJECTID and p.CHANGENR = h.CHANGENR
