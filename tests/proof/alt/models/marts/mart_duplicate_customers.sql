select
    duplicate_group_count,
    total_merged_accounts,
    remapped_order_count,
    remapped_revenue_eur
from {{ ref('int_duplicate_group_orders') }}
