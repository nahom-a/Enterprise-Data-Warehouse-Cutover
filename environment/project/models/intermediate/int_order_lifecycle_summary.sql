select
    order_id,
    state,
    changed_at
from (
    select
        order_id,
        state,
        changed_at,
        row_number() over (partition by order_id order by changed_at desc, event_id desc) as rn
    from {{ ref('stg_order_lifecycle') }}
) ranked
where rn = 1
