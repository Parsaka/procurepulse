{#- SAP stores dates as CHAR(8) 'YYYYMMDD' (DATS) and times as CHAR(6) 'HHMMSS' (TIMS).
    '00000000' and blanks mean "no date". These macros turn them into timestamps on
    both warehouses. -#}

{% macro sap_timestamp(dats, tims) -%}
    {{ return(adapter.dispatch('sap_timestamp', 'procurepulse')(dats, tims)) }}
{%- endmacro %}

{% macro default__sap_timestamp(dats, tims) -%}
    case when nullif(trim({{ dats }}), '') is null or {{ dats }} = '00000000' then null
         else strptime({{ dats }} || coalesce(nullif(trim({{ tims }}), ''), '000000'), '%Y%m%d%H%M%S') end
{%- endmacro %}

{% macro snowflake__sap_timestamp(dats, tims) -%}
    case when nullif(trim({{ dats }}), '') is null or {{ dats }} = '00000000' then null
         else to_timestamp_ntz({{ dats }} || coalesce(nullif(trim({{ tims }}), ''), '000000'), 'YYYYMMDDHH24MISS') end
{%- endmacro %}

{#- Remove leading zeros from SAP CHAR keys for display (ALPHA conversion exit, output side) -#}
{% macro sap_alpha_out(col) -%}
    coalesce(nullif(ltrim({{ col }}, '0'), ''), '0')
{%- endmacro %}

{#- 'X' / '' flags to boolean -#}
{% macro sap_flag(col) -%}
    (coalesce(trim({{ col }}), '') = 'X')
{%- endmacro %}
