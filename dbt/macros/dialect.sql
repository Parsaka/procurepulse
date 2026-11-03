{#- Small dialect helpers so every model compiles on DuckDB and Snowflake. -#}

{% macro hours_between(start_ts, end_ts) -%}
    {{ return(adapter.dispatch('hours_between', 'procurepulse')(start_ts, end_ts)) }}
{%- endmacro %}
{% macro default__hours_between(start_ts, end_ts) -%}
    (date_diff('second', {{ start_ts }}, {{ end_ts }}) / 3600.0)
{%- endmacro %}
{% macro snowflake__hours_between(start_ts, end_ts) -%}
    (datediff('second', {{ start_ts }}, {{ end_ts }}) / 3600.0)
{%- endmacro %}

{% macro days_between(start_ts, end_ts) -%}
    ({{ hours_between(start_ts, end_ts) }} / 24.0)
{%- endmacro %}

{#- Ordered string aggregation (process variants) -#}
{% macro ordered_listagg(expr, order_by, sep=' > ') -%}
    {{ return(adapter.dispatch('ordered_listagg', 'procurepulse')(expr, order_by, sep)) }}
{%- endmacro %}
{% macro default__ordered_listagg(expr, order_by, sep) -%}
    string_agg({{ expr }}, '{{ sep }}' order by {{ order_by }})
{%- endmacro %}
{% macro snowflake__ordered_listagg(expr, order_by, sep) -%}
    listagg({{ expr }}, '{{ sep }}') within group (order by {{ order_by }})
{%- endmacro %}

{% macro md5_hash(expr) -%}
    md5(cast({{ expr }} as varchar))
{%- endmacro %}


{% macro month_start(col) -%}
    cast(date_trunc('month', {{ col }}) as date)
{%- endmacro %}

{% macro median(expr) -%}
    {{ return(adapter.dispatch('median', 'procurepulse')(expr)) }}
{%- endmacro %}
{% macro default__median(expr) -%}
    median({{ expr }})
{%- endmacro %}

{% macro percentile(expr, p) -%}
    {{ return(adapter.dispatch('percentile', 'procurepulse')(expr, p)) }}
{%- endmacro %}
{% macro default__percentile(expr, p) -%}
    quantile_cont({{ expr }}, {{ p }})
{%- endmacro %}
{% macro snowflake__percentile(expr, p) -%}
    percentile_cont({{ p }}) within group (order by {{ expr }})
{%- endmacro %}
