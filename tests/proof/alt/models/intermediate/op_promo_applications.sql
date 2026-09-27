select
    order_id,
    seq,
    promo_code,
    berlin_ts(applied_at) as applied_at,
    case when removed_at < m.as_of_utc then berlin_ts(removed_at) else null end as removed_at
from {{ source('platform', 'order_promo_applications') }} p
cross join {{ source('platform', 'extract_meta') }} m
where applied_at < m.as_of_utc
