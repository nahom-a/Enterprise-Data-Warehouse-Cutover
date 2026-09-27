-- REF: reproduces legacy shipments (first non-cancelled shipment).
select
    order_id,
    min(berlin_ts(shipped_at)) as shipped_at
from {{ source('platform', 'shipments') }} s
cross join {{ source('platform', 'extract_meta') }} m
where s.committed_at < m.as_of_utc
  and (s.cancelled_at is null or s.cancelled_at >= m.as_of_utc)
group by order_id
