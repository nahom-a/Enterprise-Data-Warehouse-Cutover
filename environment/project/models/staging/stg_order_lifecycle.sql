select
    id as event_id,
    order_id,
    state,
    changed_at
from {{ source('legacy', 'order_lifecycle') }}
