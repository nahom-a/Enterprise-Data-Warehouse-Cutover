select
    s.sku,
    s.category,
    sum(s.quantity) as units_sold,
    sum(s.net_eur)::decimal(18,2) as revenue_eur
from {{ ref('int_product_line_sales') }} s
group by s.sku, s.category
