select
    id, order_id, state, changed_at
from {{ ref('op_order_lifecycle') }}
