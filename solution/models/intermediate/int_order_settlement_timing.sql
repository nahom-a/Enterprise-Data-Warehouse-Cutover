select
    o.order_id,
    o.placed_at,
    min(c.day) as first_capture_day,
    max(c.amount_eur) as max_capture_amount
from {{ ref('stg_orders') }} o
join {{ ref('int_payment_captures') }} c on c.order_id = o.order_id
group by o.order_id, o.placed_at
