select
    l.order_line_id,
    l.order_id,
    l.sku,
    l.quantity,
    l.unit_price_minor,
    l.discount_minor,
    discount_ratio(l.discount_minor, l.unit_price_minor, l.quantity) as discount_rate
from {{ ref('stg_order_lines') }} l
