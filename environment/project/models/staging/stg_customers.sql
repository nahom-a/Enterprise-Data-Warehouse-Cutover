select
    id as customer_id,
    email,
    segment,
    region,
    last_login_ip
from {{ source('legacy', 'customers') }}
