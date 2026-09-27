select
    customer_id,
    start_of_month(cast(placed_at as date)) as cohort_month,
    order_id as first_order_id,
    placed_at as first_placed_at
from {{ ref('int_customer_first_order') }}
