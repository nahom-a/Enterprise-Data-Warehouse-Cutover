select
    customer_id,
    order_id,
    placed_at
from (
    select
        customer_id,
        order_id,
        placed_at,
        row_number() over (partition by customer_id order by placed_at, order_id) as rn
    from {{ ref('stg_orders') }}
    where customer_id is not null and customer_id != 0
) ranked
where rn = 1
