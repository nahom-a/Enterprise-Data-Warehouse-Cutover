CREATE OR REPLACE MACRO start_of_month(d) AS
    CAST(date_trunc('month', d::TIMESTAMP) AS DATE);

CREATE OR REPLACE MACRO hours_between(start_ts, end_ts) AS
    CAST(round_even(date_diff('minute', start_ts::TIMESTAMP, end_ts::TIMESTAMP) / 60.0, 2) AS DECIMAL(18,2));
