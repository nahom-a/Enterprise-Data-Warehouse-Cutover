select
    order_id, shipped_at
from {{ ref('extract_shipments') }}
