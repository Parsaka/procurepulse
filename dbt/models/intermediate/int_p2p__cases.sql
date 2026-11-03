-- One row per PO item (the process case) with SAP master data joined in.
-- The item category that defines the target process is derived from SAP fields,
-- exactly as a P2P analyst would do it in a real system:
--   consignment (PSTYP 2)            -> no invoice expected in this flow
--   no GR expected (WEPOS '')        -> 2-way match
--   GR expected + GR-based IV        -> 3-way match, invoice after GR
--   GR expected, no GR-based IV      -> 3-way match, invoice before GR allowed
select
    i.case_key,
    i.purchase_order_id,
    i.purchase_order_item,
    {{ sap_alpha_out('i.purchase_order_id') }} || '/' || {{ sap_alpha_out('i.purchase_order_item') }} as case_label,
    h.company_code,
    h.document_type,
    h.vendor_id,
    i.item_category_code,
    case
        when i.item_category_code = '2'            then 'Consignment'
        when not i.is_goods_receipt_expected       then '2-way match'
        when i.is_gr_based_invoice_verification    then '3-way match, invoice after GR'
        else                                            '3-way match, invoice before GR'
    end                                           as item_category,
    i.is_goods_receipt_expected,
    i.is_gr_based_invoice_verification,
    i.material_group,
    m.spend_area,
    m.sub_spend_area,
    m.spend_classification,
    i.net_value_eur,
    i.created_at,
    i.created_by
from {{ ref('stg_sap__purchase_order_items') }} i
join {{ ref('stg_sap__purchase_order_headers') }} h on h.purchase_order_id = i.purchase_order_id
left join {{ ref('stg_sap__material_groups') }} m on m.material_group = i.material_group
