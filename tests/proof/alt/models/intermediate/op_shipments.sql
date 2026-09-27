select
    shipment_id as id,
    order_id,
    berlin_ts(shipped_at) as shipped_at,
    case when cancelled_at < m.as_of_utc then berlin_ts(cancelled_at) else null end as cancelled_at
from {{ source('platform', 'shipments') }} s
cross join {{ source('platform', 'extract_meta') }} m
where committed_at < m.as_of_utc
