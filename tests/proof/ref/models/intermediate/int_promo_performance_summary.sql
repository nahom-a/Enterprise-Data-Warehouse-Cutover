select
    p.promo_code,
    count(distinct p.order_id) as total_applications,
    sum(case when p.is_active then 1 else 0 end) as active_applications
from {{ ref('int_order_promos_effective') }} p
group by p.promo_code
