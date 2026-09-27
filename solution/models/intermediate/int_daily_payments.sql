select
    day,
    sum(case when is_capture(kind) then amount_eur else 0 end)::decimal(18,2) as captured_eur,
    sum(case when is_refund(kind) then amount_eur else 0 end)::decimal(18,2) as refunded_eur
from {{ ref('int_payment_flows') }}
group by day
