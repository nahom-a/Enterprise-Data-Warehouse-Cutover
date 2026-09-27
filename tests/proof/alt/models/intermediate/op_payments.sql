select
    p.payment_id as id,
    p.order_id,
    p.kind,
    p.amount_minor,
    p.currency,
    eur_amount(
        p.amount_minor,
        c.exponent,
        case
            when p.currency = 'EUR' then 1.0
            else (
                select f.rate_to_eur
                from {{ source('platform', 'fx_daily') }} f
                where f.currency = p.currency
                  and f.date <= effective_fx_date(p.committed_at)
                order by f.date desc
                limit 1
            )
        end
    ) as amount_eur,
    berlin_ts(p.occurred_at) as occurred_at,
    berlin_ts(p.committed_at) as recorded_at
from {{ source('platform', 'payment_events') }} p
join {{ source('platform', 'currencies') }} c on c.code = p.currency
cross join {{ source('platform', 'extract_meta') }} m
where p.committed_at < m.as_of_utc
