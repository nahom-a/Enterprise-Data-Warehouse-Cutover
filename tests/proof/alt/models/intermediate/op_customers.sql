with ranked as (
    select
        v.customer_id as id,
        v.email,
        v.segment,
        v.region,
        row_number() over (partition by v.customer_id order by v.valid_from desc) as rn
    from {{ source('platform', 'customer_versions') }} v
    cross join {{ source('platform', 'extract_meta') }} m
    where v.valid_from < m.as_of_utc
),
stat as (
    select
        customer_id,
        event_type,
        committed_at,
        row_number() over (partition by customer_id order by committed_at desc) as rn
    from {{ source('platform', 'customer_status_events') }}
    cross join {{ source('platform', 'extract_meta') }} m
    where committed_at < m.as_of_utc
)
select
    r.id,
    r.email,
    r.segment,
    r.region,
    case
        when s.event_type = 'deleted' then berlin_ts(s.committed_at)
        else null
    end as deleted_at,
    cast(null as varchar) as last_login_ip
from ranked r
left join (select * from stat where rn = 1) s on s.customer_id = r.id
where r.rn = 1
