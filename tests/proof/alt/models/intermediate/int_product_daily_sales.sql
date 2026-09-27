select
    r.day,
    s.sku,
    s.category,
    sum(s.quantity) as daily_units,
    sum(s.net_eur)::decimal(18,2) as daily_revenue_eur
from {{ ref('int_product_line_sales') }} s
join {{ ref('int_order_line_revenue') }} r on r.order_line_id = s.order_line_id
group by r.day, s.sku, s.category
