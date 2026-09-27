select
    sku, name, category from {{ ref('extract_products') }}
