select company_code, company_name, currency from {{ ref('stg_sap__company_codes') }}
