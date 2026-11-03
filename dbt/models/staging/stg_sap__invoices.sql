-- RBKP: logistics invoice verification. TBTKZ 'X' = subsequent debit/credit.
select
    BELNR                                   as invoice_id,
    GJAHR                                   as fiscal_year,
    ZZ_EBELN || ZZ_EBELP                    as case_key,
    VGART                                   as transaction_type,
    {{ sap_flag('TBTKZ') }}                 as is_subsequent_debit_credit,
    {{ sap_flag('ZZ_IS_REVERSAL') }}        as is_reversal,
    {{ sap_timestamp('CPUDT', 'CPUTM') }}   as posted_at,
    cast(RMWWR as double)                   as gross_amount_eur,
    USNAM                                   as created_by,
    cast(ZZ_EVENT_SEQ as integer)           as event_seq
from {{ source('sap', 'RBKP') }}
