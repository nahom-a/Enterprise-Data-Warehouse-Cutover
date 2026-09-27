select
    date, currency, rate_to_eur from {{ ref('extract_fx_rates') }}
