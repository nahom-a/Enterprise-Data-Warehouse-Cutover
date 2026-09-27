select
    customer_id,
    email,
    segment,
    region
from {{ ref('stg_customers') }}
where customer_id != 0
