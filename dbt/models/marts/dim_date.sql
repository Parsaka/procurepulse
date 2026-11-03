-- Calendar for the analysis window
with recursive days (date_day) as (
    select cast('{{ var("window_start") }}' as date)
    union all
    select cast({{ dbt.dateadd('day', 1, 'date_day') }} as date)
    from days
    where date_day < cast('{{ var("window_end") }}' as date) - 1
)
select
    date_day,
    extract(year from date_day)                as year,
    extract(month from date_day)               as month,
    extract(quarter from date_day)             as quarter,
    {{ month_start('date_day') }}              as month_start,
    extract(dayofweek from date_day) in (0, 6) as is_weekend
from days
