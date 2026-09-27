select
    day,
    currency,
    revenue_eur,
    order_count
from {{ ref('int_line_revenue_by_day') }}
