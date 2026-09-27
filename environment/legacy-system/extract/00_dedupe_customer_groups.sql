create table _customer_canonical as
select
    lower(email) as email_key,
    min(id)      as canonical_id
from op_customers
where deleted_at is null
group by lower(email);
create table _customer_dedupe_map as
select
    c.id            as member_id,
    lower(c.email)  as email_key,
    canon.canonical_id
from op_customers c
join _customer_canonical canon
    on canon.email_key = lower(c.email);
