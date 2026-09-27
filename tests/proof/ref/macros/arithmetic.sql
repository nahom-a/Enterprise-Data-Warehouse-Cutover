-- Exact round-half-even, staying in DECIMAL/HUGEINT arithmetic throughout.
-- DuckDB's round_even() always evaluates through DOUBLE regardless of input type, which
-- can flip an exact .xx5 tie the wrong way (verified: round_even(1.005::DECIMAL, 2) = 1.01,
-- not the correct banker's-rounding 1.00). This scales to an integer number of units,
-- floors, and resolves ties on the exact DECIMAL remainder instead of a float comparison.
CREATE OR REPLACE MACRO round_half_even_exact(x, scale_factor) AS (
    CASE
        WHEN (x * scale_factor - FLOOR(x * scale_factor)) < 0.5
            THEN FLOOR(x * scale_factor)
        WHEN (x * scale_factor - FLOOR(x * scale_factor)) > 0.5
            THEN FLOOR(x * scale_factor) + 1
        WHEN CAST(FLOOR(x * scale_factor) AS HUGEINT) % 2 = 0
            THEN FLOOR(x * scale_factor)
        ELSE FLOOR(x * scale_factor) + 1
    END::DECIMAL(38,10) / scale_factor
);
