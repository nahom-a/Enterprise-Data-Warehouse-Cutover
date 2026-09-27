select
    id, order_id, sku, quantity, unit_price_minor, discount_minor, currency, net_eur
from {{ ref('op_order_lines') }}
