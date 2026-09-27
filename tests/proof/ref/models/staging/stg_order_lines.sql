-- REF: reproduces legacy order_lines.
select
    l.order_line_id,
    l.order_id,
    l.sku,
    l.quantity,
    l.unit_price_minor,
    l.discount_minor,
    l.currency,
    eur_amount(
        l.unit_price_minor * l.quantity - l.discount_minor,
        c.exponent,
        case
            when l.currency = 'EUR' then 1.0
            else (
                select f.rate_to_eur
                from {{ source('platform', 'fx_daily') }} f
                where f.currency = l.currency
                  and f.date <= effective_fx_date(o.committed_at)
                order by f.date desc
                limit 1
            )
        end
    ) as net_eur
from {{ source('platform', 'order_lines') }} l
join {{ source('platform', 'orders') }} o on o.order_id = l.order_id
join {{ source('platform', 'currencies') }} c on c.code = l.currency
cross join {{ source('platform', 'extract_meta') }} m
where l.committed_at < m.as_of_utc
