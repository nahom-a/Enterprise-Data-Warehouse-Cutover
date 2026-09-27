CREATE OR REPLACE MACRO is_refund(kind_val) AS
    (kind_val = 'refund');

CREATE OR REPLACE MACRO is_capture(kind_val) AS
    (kind_val = 'capture');
