select
    f.customer_id,
    f.order_id,
    f.placed_at,
    coalesce(o.segment, 'UNKNOWN') as segment,
    o.total_eur
from {{ ref('int_customer_first_order') }} f
join {{ ref('int_orders_enriched') }} o on o.order_id = f.order_id
