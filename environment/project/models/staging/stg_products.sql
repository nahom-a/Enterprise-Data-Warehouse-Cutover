select
    sku,
    name,
    category
from {{ source('legacy', 'products') }}
