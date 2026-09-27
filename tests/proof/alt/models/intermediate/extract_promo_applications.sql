select
    order_id, seq, promo_code, applied_at, removed_at
from {{ ref('op_promo_applications') }}
