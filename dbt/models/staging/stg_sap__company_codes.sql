select BUKRS as company_code, BUTXT as company_name, WAERS as currency
from {{ source('sap', 'T001') }}
