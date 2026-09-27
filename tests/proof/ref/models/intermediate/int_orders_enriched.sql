select
    o.order_id,
    o.customer_id,
    c.segment,
    c.region,
    o.placed_at,
    o.total_eur,
    o.status,
    o.promo_id
from {{ ref('stg_orders') }} o
left join {{ ref('stg_customers') }} c on c.customer_id = o.customer_id
