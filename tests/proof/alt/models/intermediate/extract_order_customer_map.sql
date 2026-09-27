with registered as (
    select
        o.id as order_id,
        coalesce(m.canonical_id, o.customer_id) as customer_id
    from {{ ref('op_orders') }} o
    left join {{ ref('extract_customer_dedupe_map') }} m
        on m.member_id = o.customer_id
    where o.customer_id is not null
),
guest_linked as (
    select
        o.id as order_id,
        canon.canonical_id as customer_id
    from {{ ref('op_orders') }} o
    join {{ ref('extract_customer_canonical') }} canon
        on canon.email_key = lower(o.guest_email)
    where o.customer_id is null
      and o.guest_email is not null
),
guest_unmatched as (
    select
        o.id as order_id,
        0 as customer_id
    from {{ ref('op_orders') }} o
    where o.customer_id is null
      and o.id not in (select order_id from guest_linked)
)
select * from registered
union all
select * from guest_linked
union all
select * from guest_unmatched
