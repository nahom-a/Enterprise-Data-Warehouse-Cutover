CREATE OR REPLACE MACRO discount_ratio(disc_minor, unit_minor, qty) AS
    CASE
        WHEN (unit_minor * qty) = 0 THEN CAST(0.00 AS DECIMAL(18,4))
        ELSE CAST(round_half_even_exact(disc_minor::DECIMAL(38,10) / (unit_minor * qty)::DECIMAL(38,10), 10000) AS DECIMAL(18,4))
    END;
