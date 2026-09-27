select
    coalesce(segment, 'UNKNOWN') as segment,
    order_id,
    total_eur
from {{ ref('int_orders_enriched') }}
