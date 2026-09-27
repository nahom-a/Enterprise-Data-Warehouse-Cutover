create table payments as
select
    id,
    order_id,
    kind,
    amount_minor,
    currency,
    amount_eur,
    occurred_at,
    recorded_at
from op_payments;
