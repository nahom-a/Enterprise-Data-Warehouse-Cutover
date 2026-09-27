select
    c.segment,
    c.region,
    count(distinct c.customer_id) as customer_count,
    coalesce(sum(s.total_spend_eur), 0)::decimal(18,2) as segment_spend_eur
from {{ ref('int_customers_active') }} c
left join {{ ref('int_customer_order_summary') }} s on s.customer_id = c.customer_id
group by c.segment, c.region
