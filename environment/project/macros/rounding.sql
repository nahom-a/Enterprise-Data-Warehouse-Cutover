CREATE OR REPLACE MACRO cents(amount_dec) AS
    CAST(round_even(amount_dec, 2) AS DECIMAL(18,2));

CREATE OR REPLACE MACRO ratio_pct(num, den) AS
    CASE
        WHEN den IS NULL OR den = 0 THEN CAST(NULL AS DECIMAL(18,2))
        ELSE CAST(round_even((num::DECIMAL(18,6) / den::DECIMAL(18,6)) * 100.0, 2) AS DECIMAL(18,2))
    END;
