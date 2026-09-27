select
    g.is_unmatched_guest,
    g.is_guest_attributed,
    count(distinct g.order_id) as order_count,
    sum(g.total_eur)::decimal(18,2) as revenue_eur
from {{ ref('int_guest_order_classification') }} g
group by g.is_unmatched_guest, g.is_guest_attributed
