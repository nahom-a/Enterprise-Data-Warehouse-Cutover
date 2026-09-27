select
    region,
    count(distinct order_id) as order_count,
    sum(total_eur)::decimal(18,2) as total_eur
from {{ ref('int_orders_by_region') }}
group by region
