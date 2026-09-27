select
    c.customer_id,
    c.segment,
    c.region,
    coalesce(s.total_orders, 0) as order_count,
    coalesce(s.total_spend_eur, 0)::decimal(18,2) as total_spend_eur,
    s.first_placed_at,
    s.last_placed_at
from {{ ref('int_customers_active') }} c
left join {{ ref('int_customer_order_summary') }} s on s.customer_id = c.customer_id
