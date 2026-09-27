select
    id as order_id, customer_id, channel, placed_at, total_eur, status, promo_id
from {{ ref('extract_orders') }}
