select
    status,
    order_count,
    total_eur
from {{ ref('int_status_order_summary') }}
