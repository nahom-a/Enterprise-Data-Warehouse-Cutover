select
    currency,
    kind,
    count(*) as payment_count,
    sum(amount_eur)::decimal(18,2) as amount_eur
from {{ ref('stg_payments') }}
group by currency, kind
