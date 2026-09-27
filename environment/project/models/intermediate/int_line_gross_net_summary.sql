select
    cast(o.placed_at as date) as day,
    sum(l.net_eur)::decimal(18,2) as net_revenue_eur,
    count(distinct o.order_id) as order_count
from {{ ref('stg_order_lines') }} l
join {{ ref('stg_orders') }} o on o.order_id = l.order_id
group by cast(o.placed_at as date)
