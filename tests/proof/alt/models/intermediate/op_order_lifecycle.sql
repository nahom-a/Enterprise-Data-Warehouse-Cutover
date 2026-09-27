select
    event_id as id,
    order_id,
    state,
    berlin_ts(committed_at) as changed_at
from {{ source('platform', 'order_lifecycle_events') }} e
cross join {{ source('platform', 'extract_meta') }} m
where committed_at < m.as_of_utc
