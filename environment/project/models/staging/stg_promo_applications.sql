select
    order_id,
    seq,
    promo_code,
    applied_at,
    removed_at
from {{ source('legacy', 'promo_applications') }}
