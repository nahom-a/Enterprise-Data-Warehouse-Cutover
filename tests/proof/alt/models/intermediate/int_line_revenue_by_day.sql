select
    day,
    currency,
    sum(net_eur)::decimal(18,2) as revenue_eur,
    count(distinct order_id) as order_count
from {{ ref('int_order_line_revenue') }}
group by day, currency
