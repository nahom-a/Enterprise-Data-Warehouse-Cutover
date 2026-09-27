select
    clean_string(email) as email_key,
    count(*) as account_count,
    min(customer_id) as canonical_id
from {{ ref('stg_customers') }}
where customer_id != 0
group by clean_string(email)
