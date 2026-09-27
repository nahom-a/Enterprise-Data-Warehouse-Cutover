select
    d.email_key,
    d.canonical_id,
    d.account_count,
    count(distinct o.order_id) as mapped_order_count,
    coalesce(sum(o.total_eur), 0)::decimal(18,2) as mapped_revenue_eur
from {{ ref('int_duplicate_account_clusters') }} d
join {{ ref('stg_orders') }} o on o.customer_id = d.canonical_id
where d.account_count > 1
group by d.email_key, d.canonical_id, d.account_count
