
CREATE OR REPLACE MACRO eur_amount(amount_minor, exponent, rate) AS
    CAST(
        round_even(
            (amount_minor::DECIMAL(18,6) / CAST(POWER(10, exponent) AS DECIMAL(18,6)))
                * rate::DECIMAL(18,6),
            2
        ) AS DECIMAL(18,2)
    );

CREATE OR REPLACE MACRO berlin_ts(utc_ts) AS
    (utc_ts AT TIME ZONE 'Europe/Berlin');

CREATE OR REPLACE MACRO berlin_date(utc_ts) AS
    CAST(berlin_ts(utc_ts) AS DATE);
