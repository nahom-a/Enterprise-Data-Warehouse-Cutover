select
    customer_id,
    segment,
    order_count,
    total_spend_eur as lifetime_spend_eur,
    avg_order_value_eur
from {{ ref('int_customer_lifetime_aggregates') }}
