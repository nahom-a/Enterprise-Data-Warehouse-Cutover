-- REF: reproduces the legacy orders table.
with base_orders as (
    select
        o.order_id,
        o.customer_id,
        o.guest_email,
        berlin_ts(o.committed_at) as placed_at,
        o.committed_at as placed_at_utc
    from {{ source('platform', 'orders') }} o
    cross join {{ source('platform', 'extract_meta') }} m
    where o.committed_at < m.as_of_utc
),
ranked_versions as (
    select
        v.customer_id,
        v.email,
        row_number() over (partition by v.customer_id order by v.valid_from desc) as rn
    from {{ source('platform', 'customer_versions') }} v
    cross join {{ source('platform', 'extract_meta') }} m
    where v.valid_from < m.as_of_utc
),
current_versions as (
    select customer_id, email
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
),
dedupe_map as (
    select
        c.customer_id as member_id,
        canon.canonical_id
    from current_versions c
    join canonical_active canon on canon.email_key = lower(c.email)
),
resolved_orders as (
    select
        b.order_id,
        coalesce(cust_stat.event_type, '') as cust_status,
        case
            when b.customer_id is not null then coalesce(d.canonical_id, b.customer_id)
            when b.guest_email is not null and g.canonical_id is not null then g.canonical_id
            else 0
        end as customer_id,
        b.placed_at,
        b.placed_at_utc
    from base_orders b
    left join dedupe_map d on d.member_id = b.customer_id
    left join canonical_active g on g.email_key = lower(b.guest_email)
    left join (select customer_id, event_type from status_latest where rn = 1) cust_stat
        on cust_stat.customer_id = b.customer_id
),
lifecycle_current as (
    select order_id, state
    from (
        select
            order_id,
            state,
            row_number() over (partition by order_id order by committed_at desc, event_id desc) as rn
        from {{ source('platform', 'order_lifecycle_events') }} e
        cross join {{ source('platform', 'extract_meta') }} m
        where e.committed_at < m.as_of_utc
    ) ranked
    where rn = 1
),
line_totals as (
    select order_id, sum(net_eur)::decimal(18,2) as total_eur
    from {{ ref('stg_order_lines') }}
    group by order_id
),
pay_sums as (
    select
        order_id,
        sum(case when kind = 'capture' then amount_eur else 0 end) as captured,
        sum(case when kind = 'refund' then amount_eur else 0 end) as refunded
    from {{ ref('stg_payments') }}
    group by order_id
),
winning_promos as (
    select order_id, promo_code
    from (
        select
            p.order_id,
            p.promo_code,
            row_number() over (partition by p.order_id order by p.seq) as rn
        from {{ ref('stg_promo_applications') }} p
        where p.removed_at is null
    ) ranked
    where rn = 1
),
first_captures as (
    select
        order_id,
        min(committed_at) as first_capture_at
    from {{ source('platform', 'payment_events') }} p
    cross join {{ source('platform', 'extract_meta') }} m
    where p.kind = 'capture'
      and p.committed_at < m.as_of_utc
    group by order_id
),
first_fulfills as (
    select
        order_id,
        min(committed_at) as first_fulfilled_at
    from {{ source('platform', 'order_lifecycle_events') }} e
    cross join {{ source('platform', 'extract_meta') }} m
    where e.state = 'fulfilled'
      and e.committed_at < m.as_of_utc
    group by order_id
),
cust_deletions as (
    select distinct b.order_id
    from base_orders b
    cross join {{ source('platform', 'extract_meta') }} m
    join {{ source('platform', 'customer_status_events') }} s
        on s.customer_id = b.customer_id
       and s.event_type = 'deleted'
       and s.committed_at > b.placed_at_utc
       and s.committed_at < m.as_of_utc
    left join first_captures fc on fc.order_id = b.order_id
    left join first_fulfills ff on ff.order_id = b.order_id
    where (fc.first_capture_at is null or s.committed_at < fc.first_capture_at)
      and (ff.first_fulfilled_at is null or s.committed_at < ff.first_fulfilled_at)
)
select
    r.order_id,
    r.customer_id,
    cast(null as varchar) as channel,
    r.placed_at,
    r.placed_at_utc,
    coalesce(lt.total_eur, 0)::decimal(18,2) as total_eur,
    case
        when coalesce(ps.refunded, 0) >= coalesce(ps.captured, 0) and coalesce(ps.captured, 0) > 0
            then 'refunded'
        when coalesce(ps.refunded, 0) > 0
            then 'partially_refunded'
        when lc.state = 'cancelled'
             or cd.order_id is not null
            then 'cancelled'
        when lc.state = 'fulfilled'
            then 'shipped'
        when coalesce(ps.captured, 0) > 0
            then 'paid'
        else 'pending'
    end as status,
    wp.promo_code as promo_id
from resolved_orders r
left join line_totals lt on lt.order_id = r.order_id
left join pay_sums ps on ps.order_id = r.order_id
left join lifecycle_current lc on lc.order_id = r.order_id
left join winning_promos wp on wp.order_id = r.order_id
left join cust_deletions cd on cd.order_id = r.order_id
