create table order_lifecycle as
select
    id,
    order_id,
    state,
    changed_at
from op_order_lifecycle;
