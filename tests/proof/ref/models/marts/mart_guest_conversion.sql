select
    is_unmatched_guest,
    is_guest_attributed,
    order_count,
    revenue_eur
from {{ ref('int_guest_order_revenue') }}
