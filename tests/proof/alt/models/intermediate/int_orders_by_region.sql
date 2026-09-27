select
    default_region(region) as region,
    order_id,
    total_eur
from {{ ref('int_orders_enriched') }}
