select
    day,
    currency,
    kind,
    sum(amount_eur)::decimal(18,2) as exposure_eur
from {{ ref('int_payment_flows') }}
group by day, currency, kind
