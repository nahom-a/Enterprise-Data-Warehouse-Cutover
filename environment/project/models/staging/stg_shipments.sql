select
    order_id,
    shipped_at
from {{ source('legacy', 'shipments') }}
