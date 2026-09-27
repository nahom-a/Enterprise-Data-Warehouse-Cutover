create table customers as
select
    c.id,
    c.email,
    c.segment,
    c.region,
    c.last_login_ip
from op_customers c
join _customer_canonical canon
    on canon.canonical_id = c.id
where c.deleted_at is null
union all
select
    0            as id,
    'guest'      as email,
    null         as segment,
    null         as region,
    null         as last_login_ip;
