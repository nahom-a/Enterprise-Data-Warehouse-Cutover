select
    payment_id,
    order_id,
    day,
    currency,
    amount_eur
from {{ ref('int_payment_flows') }}
where is_capture(kind)
