select
    order_id,
    customer_id,
    placed_at,
    shipped_at,
    is_shipped,
    case
        when is_shipped then hours_between(placed_at, shipped_at)
        else null
    end as lead_time_hours
from {{ ref('int_order_shipping_status') }}
