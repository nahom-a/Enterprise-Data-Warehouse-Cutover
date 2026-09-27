CREATE OR REPLACE MACRO cents(amount_dec) AS
    CAST(round_half_even_exact(amount_dec::DECIMAL(38,10), 100) AS DECIMAL(18,2));

CREATE OR REPLACE MACRO ratio_pct(num, den) AS
    CASE
        WHEN den IS NULL OR den = 0 THEN CAST(NULL AS DECIMAL(18,2))
        ELSE CAST(round_half_even_exact((num::DECIMAL(38,10) / den::DECIMAL(38,10)) * 100.0, 100) AS DECIMAL(18,2))
    END;
