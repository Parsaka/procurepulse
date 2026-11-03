-- The item category derived from EKPO fields (PSTYP, WEPOS, WEBRE) must equal the
-- label in the source log for every PO item.
select c.case_key, c.item_category as derived, a.ITEM_CATEGORY as source_label
from {{ ref('int_p2p__cases') }} c
join {{ source('sap', 'ZZ_AUDIT_CASE_LABELS') }} a on a.CASE_KEY = c.case_key
where c.item_category <> a.ITEM_CATEGORY
