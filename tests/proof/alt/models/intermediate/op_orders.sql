with base_orders as (
    select
        o.order_id as id,
        o.customer_id,
        o.guest_email,
        cast(null as varchar) as channel,
        berlin_ts(o.committed_at) as placed_at,
        o.committed_at as placed_at_utc
    from {{ source('platform', 'orders') }} o
    cross join {{ source('platform', 'extract_meta') }} m
    where o.committed_at < m.as_of_utc
),
line_totals as (
    select order_id, sum(net_eur)::decimal(18,2) as total_eur
    from {{ ref('op_order_lines') }}
    group by order_id
),
pay_sums as (
    select
        order_id,
        sum(case when kind = 'capture' then amount_eur else 0 end) as captured,
        sum(case when kind = 'refund' then amount_eur else 0 end) as refunded
    from {{ ref('op_payments') }}
    group by order_id
),
lifecycle_current as (
    select order_id, state
    from (
        select
            order_id,
            state,
            row_number() over (partition by order_id order by changed_at desc, id desc) as rn
        from {{ ref('op_order_lifecycle') }}
    ) ranked
    where rn = 1
),
winning_promos as (
    select order_id, promo_code
    from (
        select
            p.order_id,
            p.promo_code,
            row_number() over (
                partition by p.order_id
                order by p.seq, p.applied_at
            ) as rn
        from {{ ref('op_promo_applications') }} p
        left join line_totals lt on lt.order_id = p.order_id
        where p.removed_at is null
          and not (p.promo_code like 'PROMO-SAVE%' and coalesce(lt.total_eur, 0) < 40.00)
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
first_cancellations as (
    select
        order_id,
        min(committed_at) as first_cancelled_at
    from {{ source('platform', 'order_lifecycle_events') }} e
    cross join {{ source('platform', 'extract_meta') }} m
    where e.state = 'cancelled'
      and e.committed_at < m.as_of_utc
    group by order_id
),
cust_deletions as (
    select distinct b.id as order_id
    from base_orders b
    cross join {{ source('platform', 'extract_meta') }} m
    join {{ source('platform', 'customer_status_events') }} s
        on s.customer_id = b.customer_id
       and s.event_type = 'deleted'
       and s.committed_at > b.placed_at_utc
       and s.committed_at < m.as_of_utc
    left join first_captures fc on fc.order_id = b.id
    left join first_fulfills ff on ff.order_id = b.id
    where (fc.first_capture_at is null or s.committed_at < fc.first_capture_at)
      and (ff.first_fulfilled_at is null or s.committed_at < ff.first_fulfilled_at)
)
select
    b.id,
    b.customer_id,
    b.guest_email,
    b.channel,
    b.placed_at,
    coalesce(lt.total_eur, 0)::decimal(18,2) as total_eur,
    case
        when coalesce(ps.refunded, 0) >= coalesce(ps.captured, 0) and coalesce(ps.captured, 0) > 0
            then 'refunded'
        when coalesce(ps.refunded, 0) > 0
            then 'partially_refunded'
        when fcan.order_id is not null
             or cd.order_id is not null
            then 'cancelled'
        when lc.state = 'fulfilled'
            then 'shipped'
        when coalesce(ps.captured, 0) > 0
            then 'paid'
        else 'pending'
    end as status,
    wp.promo_code as promo_id
from base_orders b
left join line_totals lt on lt.order_id = b.id
left join pay_sums ps on ps.order_id = b.id
left join lifecycle_current lc on lc.order_id = b.id
left join winning_promos wp on wp.order_id = b.id
left join {{ ref('op_customers') }} c on c.id = b.customer_id
left join cust_deletions cd on cd.order_id = b.id
left join first_cancellations fcan on fcan.order_id = b.id
