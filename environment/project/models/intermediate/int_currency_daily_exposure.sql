select
    day,
    currency,
    sum(exposure_eur)::decimal(18,2) as total_exposure_eur
from {{ ref('int_fx_exposure_by_day') }}
group by day, currency
