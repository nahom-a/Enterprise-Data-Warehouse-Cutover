create table promo_applications as
select
    order_id,
    seq,
    promo_code,
    applied_at,
    removed_at
from op_promo_applications;
