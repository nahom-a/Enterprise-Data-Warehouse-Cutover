select
    coalesce(c.segment, 'UNKNOWN') as segment,
    l.order_id,
    l.lead_time_hours,
    l.is_shipped
from {{ ref('int_shipping_lead_time_calc') }} l
left join {{ ref('stg_customers') }} c on c.customer_id = l.customer_id
