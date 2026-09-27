select
    p.category,
    sum(s.quantity) as category_units,
    sum(s.net_eur)::decimal(18,2) as category_revenue_eur
from {{ ref('int_product_line_sales') }} s
join {{ ref('int_products_catalog') }} p on p.sku = s.sku
group by p.category
