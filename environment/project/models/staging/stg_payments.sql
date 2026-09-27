select
    id as payment_id,
    order_id,
    kind,
    amount_minor,
    currency,
    amount_eur,
    occurred_at,
    recorded_at as committed_at
from {{ source('legacy', 'payments') }}
