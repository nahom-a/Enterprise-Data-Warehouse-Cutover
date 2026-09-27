select
    date, currency, rate_to_eur from {{ ref('op_fx_rates') }}
