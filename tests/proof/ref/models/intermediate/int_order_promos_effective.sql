select
    p.order_id,
    p.promo_code,
    p.seq,
    p.applied_at,
    p.removed_at,
    case when p.removed_at is null then true else false end as is_active
from {{ ref('stg_promo_applications') }} p
