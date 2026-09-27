select
    order_id,
    sku,
    sum(quantity) as sku_quantity,
    sum(net_eur)::decimal(18,2) as sku_net_eur
from {{ ref('int_order_line_revenue') }}
group by order_id, sku
