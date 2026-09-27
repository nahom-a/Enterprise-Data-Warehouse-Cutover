CREATE OR REPLACE MACRO is_settled_order(status_val) AS
    (status_val IN ('paid', 'shipped', 'partially_refunded', 'refunded'));
