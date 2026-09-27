select
    sku,
    name,
    category
from {{ ref('stg_products') }}
