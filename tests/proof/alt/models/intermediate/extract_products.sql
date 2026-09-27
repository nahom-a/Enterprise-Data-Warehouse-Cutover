select
    sku, name, category from {{ ref('op_products') }}
