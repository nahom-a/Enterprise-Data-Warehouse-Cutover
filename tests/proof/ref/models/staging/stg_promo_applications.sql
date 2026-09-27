-- REF: reproduces legacy promo_applications.
select
    p.order_id,
    p.seq,
    p.promo_code,
    berlin_ts(p.applied_at) as applied_at,
    case
        when p.removed_at is not null and p.removed_at < m.as_of_utc
            then berlin_ts(p.removed_at)
        else null
    end as removed_at
from {{ source('platform', 'order_promo_applications') }} p
cross join {{ source('platform', 'extract_meta') }} m
where p.applied_at < m.as_of_utc
