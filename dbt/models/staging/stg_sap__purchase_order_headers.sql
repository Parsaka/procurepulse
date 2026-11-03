-- EKKO: one row per purchasing document
select
    EBELN                                  as purchase_order_id,
    {{ sap_alpha_out('EBELN') }}           as purchase_order_number,
    BUKRS                                  as company_code,
    BSTYP                                  as document_category,
    BSART                                  as document_type,
    LIFNR                                  as vendor_id,
    WAERS                                  as currency,
    {{ sap_timestamp('AEDAT', "'000000'") }} as created_date,
    LOGSYS                                 as source_system
from {{ source('sap', 'EKKO') }}
