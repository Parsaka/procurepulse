{#- Use the configured schema name as-is (staging, marts, ...) instead of prefixing it
    with the target schema. Keeps object names identical on DuckDB and Snowflake. -#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}{{ target.schema }}{%- else -%}{{ custom_schema_name | trim }}{%- endif -%}
{%- endmacro %}
