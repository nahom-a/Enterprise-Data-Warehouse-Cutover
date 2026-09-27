-- REF: reproduces the legacy customers table's meaning.
-- Filters deleted accounts, deduplicates by lower(email) taking lowest active id,
-- and appends the row-0 guest pseudo-customer.
with ranked_versions as (
    select
        v.customer_id,
        v.email,
        v.segment,
        v.region,
        row_number() over (partition by v.customer_id order by v.valid_from desc) as rn
    from {{ source('platform', 'customer_versions') }} v
    cross join {{ source('platform', 'extract_meta') }} m
    where v.valid_from < m.as_of_utc
),
current_versions as (
    select customer_id, email, segment, region
    from ranked_versions
    where rn = 1
),
status_latest as (
    select
        customer_id,
        event_type,
        row_number() over (partition by customer_id order by committed_at desc) as rn
    from {{ source('platform', 'customer_status_events') }}
    cross join {{ source('platform', 'extract_meta') }} m
    where committed_at < m.as_of_utc
),
active_customers as (
    select c.*
    from current_versions c
    left join (select customer_id, event_type from status_latest where rn = 1) s
        on s.customer_id = c.customer_id
    where s.event_type is null or s.event_type != 'deleted'
),
canonical_active as (
    select
        lower(email) as email_key,
        min(customer_id) as canonical_id
    from active_customers
    group by lower(email)
)
select
    a.customer_id,
    a.email,
    a.segment,
    a.region,
    cast(null as varchar) as last_login_ip
from active_customers a
join canonical_active canon on canon.canonical_id = a.customer_id

union all

select
    0 as customer_id,
    'guest' as email,
    cast(null as varchar) as segment,
    cast(null as varchar) as region,
    cast(null as varchar) as last_login_ip
