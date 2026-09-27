select
    c.id            as member_id,
    lower(c.email)  as email_key,
    canon.canonical_id
from {{ ref('op_customers') }} c
join {{ ref('extract_customer_canonical') }} canon
    on canon.email_key = lower(c.email)
