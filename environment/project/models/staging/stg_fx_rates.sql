select
    date,
    currency,
    rate_to_eur
from {{ source('legacy', 'fx_rates') }}
