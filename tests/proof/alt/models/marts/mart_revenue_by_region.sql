select
    region,
    order_count,
    total_eur as revenue_eur
from {{ ref('int_regional_sales_breakdown') }}
