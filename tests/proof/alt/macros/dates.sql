CREATE OR REPLACE MACRO start_of_month(d) AS
    CAST(date_trunc('month', d::TIMESTAMP) AS DATE);

CREATE OR REPLACE MACRO hours_between(start_ts, end_ts) AS
    CAST(round_half_even_exact(date_diff('minute', start_ts::TIMESTAMP, end_ts::TIMESTAMP)::DECIMAL(38,10) / 60.0, 100) AS DECIMAL(18,2));
