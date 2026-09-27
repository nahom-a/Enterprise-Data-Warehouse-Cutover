select
    o.id,
    m.customer_id,
    o.channel,
    o.placed_at,
    o.total_eur,
    o.status,
    o.promo_id
from {{ ref('op_orders') }} o
join {{ ref('extract_order_customer_map') }} m
    on m.order_id = o.id
