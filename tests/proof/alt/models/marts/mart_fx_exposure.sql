select
    currency,
    kind,
    payment_count,
    amount_eur
from {{ ref('int_payment_currency_breakdown') }}
