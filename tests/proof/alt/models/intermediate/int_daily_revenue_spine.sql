select
    day,
    sum(net_eur)::decimal(18,2) as daily_revenue_eur,
    count(distinct order_id) as daily_order_count
from {{ ref('int_order_line_revenue') }}
group by day
