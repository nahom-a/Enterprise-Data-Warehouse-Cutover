select
    lower(email) as email_key,
    min(id)      as canonical_id
from {{ ref('op_customers') }}
where deleted_at is null
group by lower(email)
