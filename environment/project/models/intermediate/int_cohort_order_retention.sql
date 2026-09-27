select
    c.cohort_month,
    o.order_id,
    o.customer_id,
    o.total_eur
from {{ ref('int_customer_cohort_assignment') }} c
join {{ ref('stg_orders') }} o on o.customer_id = c.customer_id
