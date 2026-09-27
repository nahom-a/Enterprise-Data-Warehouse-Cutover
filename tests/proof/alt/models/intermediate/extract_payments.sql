select
    id, order_id, kind, amount_minor, currency, amount_eur, occurred_at, recorded_at
from {{ ref('op_payments') }}
