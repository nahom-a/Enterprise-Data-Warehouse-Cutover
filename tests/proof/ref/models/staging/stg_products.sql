-- REF: reproduces legacy products.
select
    sku,
    name,
    category
from {{ source('platform', 'products') }}
