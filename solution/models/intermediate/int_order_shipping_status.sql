select
    o.order_id,
    o.customer_id,
    o.placed_at,
    s.shipped_at,
    case when s.shipped_at is not null then true else false end as is_shipped
from {{ ref('stg_orders') }} o
left join {{ ref('stg_shipments') }} s on s.order_id = o.order_id
