select
    id as order_line_id, order_id, sku, quantity, unit_price_minor, discount_minor, currency, net_eur
from {{ ref('extract_order_lines') }}
