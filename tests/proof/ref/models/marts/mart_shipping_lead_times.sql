select
    segment,
    count(distinct order_id) as order_count,
    sum(case when is_shipped then 1 else 0 end) as shipped_count,
    coalesce(avg(lead_time_hours), 0)::decimal(18,2) as avg_hours_to_ship
from {{ ref('int_shipping_performance_summary') }}
group by segment
