select
    l.order_line_id,
    l.order_id,
    cast(o.placed_at as date) as day,
    l.sku,
    l.quantity,
    l.currency,
    l.net_eur
from {{ ref('stg_order_lines') }} l
join {{ ref('stg_orders') }} o on o.order_id = l.order_id
