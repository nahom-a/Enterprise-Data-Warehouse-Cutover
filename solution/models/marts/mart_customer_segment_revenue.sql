select
    coalesce(o.segment, 'UNKNOWN') as segment,
    sum(l.net_eur)::decimal(18,2) as revenue_eur,
    count(distinct o.order_id) as order_count
from {{ ref('int_orders_enriched') }} o
join {{ ref('int_order_line_revenue') }} l on l.order_id = o.order_id
group by o.segment
