select
    d.day,
    d.total_eur as gross_revenue_eur,
    s.daily_revenue_eur as net_revenue_eur,
    d.order_count
from {{ ref('int_daily_order_aggregates') }} d
join {{ ref('int_daily_revenue_spine') }} s on s.day = d.day
