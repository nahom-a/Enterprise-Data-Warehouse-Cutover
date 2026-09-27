select
    r.customer_id,
    r.segment,
    r.order_count,
    r.total_spend_eur,
    case
        when r.order_count = 0 then cast(0.00 as decimal(18,2))
        else cast(round_even(r.total_spend_eur / r.order_count, 2) as decimal(18,2))
    end as avg_order_value_eur
from {{ ref('int_customer_recency_frequency') }} r
