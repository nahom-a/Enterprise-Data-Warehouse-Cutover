select
    day,
    captured_eur,
    refunded_eur,
    refund_rate
from {{ ref('int_daily_refund_metrics') }}
