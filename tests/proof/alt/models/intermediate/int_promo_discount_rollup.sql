select
    o.promo_id as promo_code,
    count(distinct o.order_id) as order_count,
    sum(o.total_eur)::decimal(18,2) as promo_revenue_eur
from {{ ref('stg_orders') }} o
where o.promo_id is not null
group by o.promo_id
