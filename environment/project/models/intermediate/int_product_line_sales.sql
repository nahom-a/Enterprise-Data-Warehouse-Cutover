select
    l.order_line_id,
    l.order_id,
    l.sku,
    p.name as product_name,
    p.category,
    l.quantity,
    l.net_eur
from {{ ref('stg_order_lines') }} l
left join {{ ref('int_products_catalog') }} p on p.sku = l.sku
