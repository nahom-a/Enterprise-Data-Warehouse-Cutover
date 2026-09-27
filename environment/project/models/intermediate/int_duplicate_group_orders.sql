select
    count(distinct email_key) as duplicate_group_count,
    sum(account_count) as total_merged_accounts,
    sum(mapped_order_count) as remapped_order_count,
    sum(mapped_revenue_eur)::decimal(18,2) as remapped_revenue_eur
from {{ ref('int_duplicate_order_mapping') }}
