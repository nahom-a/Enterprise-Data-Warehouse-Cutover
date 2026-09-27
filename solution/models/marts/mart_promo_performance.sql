select
    p.promo_code,
    p.total_applications,
    p.active_applications,
    coalesce(r.promo_revenue_eur, 0)::decimal(18,2) as promo_revenue_eur
from {{ ref('int_promo_performance_summary') }} p
left join {{ ref('int_promo_discount_rollup') }} r on r.promo_code = p.promo_code
