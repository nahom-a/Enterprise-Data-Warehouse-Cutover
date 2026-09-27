select
    status,
    count(distinct order_id) as order_count,
    sum(total_eur)::decimal(18,2) as total_eur
from {{ ref('stg_orders') }}
group by status
