-- Currency conversion macro implementing exact half-even rounding to EUR cents.
-- See arithmetic.sql: round_even() goes through DOUBLE and can flip an exact-tie cent.

CREATE OR REPLACE MACRO eur_amount(amount_minor, exponent, rate) AS
    CAST(
        round_half_even_exact(
            (amount_minor::DECIMAL(38,10) / CAST(POWER(10, exponent) AS DECIMAL(38,10)))
                * rate::DECIMAL(38,10),
            100
        ) AS DECIMAL(18,2)
    );

CREATE OR REPLACE MACRO berlin_ts(utc_ts) AS
    (utc_ts AT TIME ZONE 'Europe/Berlin');

CREATE OR REPLACE MACRO berlin_date(utc_ts) AS
    CAST(berlin_ts(utc_ts) AS DATE);

CREATE OR REPLACE MACRO effective_fx_date(utc_ts) AS
    CASE
        WHEN EXTRACT(hour FROM (utc_ts AT TIME ZONE 'Europe/Berlin')) < 16
            THEN CAST(CAST(utc_ts AT TIME ZONE 'Europe/Berlin' AS DATE) - INTERVAL 1 DAY AS DATE)
        ELSE CAST(utc_ts AT TIME ZONE 'Europe/Berlin' AS DATE)
    END;
