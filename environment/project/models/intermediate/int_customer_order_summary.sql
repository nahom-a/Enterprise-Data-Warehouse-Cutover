select
    customer_id,
    count(distinct order_id) as total_orders,
    coalesce(sum(total_eur), 0)::decimal(18,2) as total_spend_eur,
    min(placed_at) as first_placed_at,
    max(placed_at) as last_placed_at
from {{ ref('stg_orders') }}
where customer_id is not null and customer_id != 0
group by customer_id
