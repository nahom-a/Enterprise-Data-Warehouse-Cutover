create table fx_rates as
select
    date,
    currency,
    rate_to_eur
from op_fx_rates;
