-- EKPO: one row per purchasing document item; the item is the process case
select
    EBELN || EBELP                          as case_key,
    EBELN                                   as purchase_order_id,
    EBELP                                   as purchase_order_item,
    PSTYP                                   as item_category_code,
    {{ sap_flag('WEPOS') }}                 as is_goods_receipt_expected,
    {{ sap_flag('WEBRE') }}                 as is_gr_based_invoice_verification,
    MATKL                                   as material_group,
    cast(NETWR as double)                   as net_value_eur,
    {{ sap_timestamp('AEDAT', 'ZZ_CPUTM') }} as created_at,
    ERNAM                                   as created_by,
    BANFN                                   as requisition_id,
    BNFPO                                   as requisition_item,
    cast(ZZ_EVENT_SEQ as integer)           as event_seq
from {{ source('sap', 'EKPO') }}
