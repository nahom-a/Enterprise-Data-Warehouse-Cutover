select
    p.payment_id,
    p.order_id,
    cast(o.placed_at as date) as day,
    p.currency,
    p.kind,
    p.amount_eur
from {{ ref('stg_payments') }} p
join {{ ref('stg_orders') }} o on o.order_id = p.order_id
