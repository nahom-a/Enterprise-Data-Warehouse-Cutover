CREATE OR REPLACE MACRO discount_ratio(disc_minor, unit_minor, qty) AS
    CASE
        WHEN (unit_minor * qty) = 0 THEN CAST(0.00 AS DECIMAL(18,4))
        ELSE CAST(round_even(disc_minor::DECIMAL(18,6) / (unit_minor * qty)::DECIMAL(18,6), 4) AS DECIMAL(18,4))
    END;
