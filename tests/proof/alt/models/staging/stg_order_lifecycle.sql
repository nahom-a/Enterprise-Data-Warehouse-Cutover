select
    id as event_id, order_id, state, changed_at
from {{ ref('extract_order_lifecycle') }}
