select
    cohort_month,
    count(distinct customer_id) as customer_count,
    count(distinct order_id) as total_orders,
    sum(total_eur)::decimal(18,2) as total_spend_eur
from {{ ref('int_cohort_order_retention') }}
group by cohort_month
