select
    id as customer_id, email, segment, region, last_login_ip
from {{ ref('extract_customers') }}
