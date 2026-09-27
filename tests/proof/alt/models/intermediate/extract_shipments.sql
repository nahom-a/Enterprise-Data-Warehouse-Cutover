select
    order_id,
    min(shipped_at) as shipped_at
from {{ ref('op_shipments') }}
where cancelled_at is null
group by order_id
