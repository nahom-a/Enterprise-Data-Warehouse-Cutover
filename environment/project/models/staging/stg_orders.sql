select
    id as order_id,
    customer_id,
    channel,
    placed_at,
    placed_at as placed_at_utc,
    total_eur,
    status,
    promo_id
from {{ source('legacy', 'orders') }}
