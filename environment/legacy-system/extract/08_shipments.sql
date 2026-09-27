create table shipments as
select
    order_id,
    min(shipped_at) as shipped_at
from op_shipments
where cancelled_at is null
group by order_id;
