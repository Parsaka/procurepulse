-- Rebuild the purchase-to-pay event log from SAP tables, the way a process mining
-- connector does: every SAP document or change becomes one event with an activity
-- name derived from SAP semantics (movement type, transaction type, changed field, ...).
with events as (

    select case_key, 'Create Purchase Requisition Item' as activity, created_at as event_at,
           created_by as user_name, value_eur as amount_eur, 'EBAN' as source_table, event_seq
    from {{ ref('stg_sap__requisition_items') }}

    union all
    select case_key, 'Create Purchase Order Item', created_at, created_by, net_value_eur, 'EKPO', event_seq
    from {{ ref('stg_sap__purchase_order_items') }}

    union all
    select case_key,
           case confirmation_kind when 'received' then 'Receive Order Confirmation'
                                  else 'Update Order Confirmation' end,
           created_at, created_by, cast(null as double), 'EKES', event_seq
    from {{ ref('stg_sap__vendor_confirmations') }}

    union all
    select case_key,
           case when is_reversal then 'Cancel Goods Receipt' else 'Record Goods Receipt' end,
           posted_at, created_by, amount_eur, 'EKBE', event_seq
    from {{ ref('stg_sap__goods_receipts') }}

    union all
    select case_key, 'Record Service Entry Sheet', created_at, created_by, amount_eur, 'ESSR', event_seq
    from {{ ref('stg_sap__service_entry_sheets') }}

    union all
    select case_key,
           case when is_subsequent_debit_credit and is_reversal then 'Cancel Subsequent Invoice'
                when is_subsequent_debit_credit then 'Record Subsequent Invoice'
                when is_reversal then 'Cancel Invoice Receipt'
                else 'Record Invoice Receipt' end,
           posted_at, created_by, gross_amount_eur, 'RBKP', event_seq
    from {{ ref('stg_sap__invoices') }}

    union all
    select case_key, 'Clear Invoice', cleared_at, created_by, amount_eur, 'BSAK', event_seq
    from {{ ref('stg_sap__cleared_vendor_items') }}

    union all
    select case_key,
           case idoc_type when 'INVOIC01' then 'Vendor creates invoice' else 'Vendor creates debit memo' end,
           created_at, cast(null as varchar), amount_eur, 'EDIDC', event_seq
    from {{ ref('stg_sap__inbound_idocs') }}

    union all
    select case_key,
           case
               when field_name = 'NETPR' then 'Change Price'
               when field_name = 'MENGE' then 'Change Quantity'
               when field_name = 'ELIKZ' then 'Change Delivery Indicator'
               when field_name = 'EREKZ' then 'Change Final Invoice Indicator'
               when field_name = 'LGORT' then 'Change Storage Location'
               when field_name = 'ABSKZ' then 'Change Rejection Indicator'
               when field_name = 'LOEKZ' and value_new = 'L' then 'Delete Purchase Order Item'
               when field_name = 'LOEKZ' and value_new = 'S' then 'Block Purchase Order Item'
               when field_name = 'LOEKZ' then 'Reactivate Purchase Order Item'
               when field_name = 'WAERS' then 'Change Currency'
               when field_name = 'FRGKE' then 'Change Approval for Purchase Order'
               when field_name = 'ZTERM' then 'Change payment term'
               when field_name = 'EKGRP' then 'Change Purchasing Group'
               when field_name = 'FRGZU' and table_name = 'EKKO' then 'Release Purchase Order'
               when field_name = 'FRGZU' and table_name = 'EBAN' then 'Release Purchase Requisition'
               when field_name = 'ZLSPR' and value_new = 'R' then 'Set Payment Block'
               when field_name = 'ZLSPR' then 'Remove Payment Block'
           end,
           changed_at, changed_by,
           case when field_name = 'NETPR' then cast(value_new as double) end,
           'CDHDR/CDPOS', event_seq
    from {{ ref('stg_sap__change_documents') }}

    union all
    select case_key, 'SRM: ' || status_text, changed_at, changed_by, cast(null as double), 'SRM_STATUS', event_seq
    from {{ ref('stg_sap__srm_status') }}

    union all
    select case_key, activity, event_at, created_by, amount_eur, 'ZZ_UNMAPPED_EVENTS', event_seq
    from {{ ref('stg_sap__unmapped_events') }}
)

select
    {{ md5_hash("case_key || '|' || cast(event_seq as varchar)") }} as event_id,
    case_key,
    activity,
    event_at,
    nullif(user_name, '')                                   as user_name,
    coalesce(user_name like 'BATCH%', false)                as is_batch_user,
    amount_eur,
    source_table,
    event_seq,
    event_at < cast('{{ var("window_start") }}' as timestamp)
        or event_at >= cast('{{ var("window_end") }}' as timestamp) as is_outside_window
from events
