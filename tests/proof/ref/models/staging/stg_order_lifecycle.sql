-- REF: reproduces legacy order_lifecycle.
select
    e.event_id,
    e.order_id,
    e.state,
    berlin_ts(e.committed_at) as changed_at
from {{ source('platform', 'order_lifecycle_events') }} e
cross join {{ source('platform', 'extract_meta') }} m
where e.committed_at < m.as_of_utc
