select
    sku, name, category from {{ source('platform', 'products') }}
