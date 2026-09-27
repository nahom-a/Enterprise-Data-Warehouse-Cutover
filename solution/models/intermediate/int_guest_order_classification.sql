select
    order_id,
    customer_id,
    case when customer_id = 0 then true else false end as is_unmatched_guest,
    case when customer_id > 0 and customer_id not in (select customer_id from {{ ref('int_customers_active') }}) then true else false end as is_guest_attributed,
    total_eur
from {{ ref('stg_orders') }}
