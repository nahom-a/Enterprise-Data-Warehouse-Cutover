select
    date, currency, rate_to_eur from {{ source('platform', 'fx_daily') }}
