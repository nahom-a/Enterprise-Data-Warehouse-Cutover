select
    p.day,
    p.captured_eur,
    p.refunded_eur,
    case
        when p.captured_eur = 0 then null
        else cast(round_even(p.refunded_eur::decimal(18,6) / p.captured_eur::decimal(18,6), 4) as decimal(18,4))
    end as refund_rate
from {{ ref('int_daily_payments') }} p
