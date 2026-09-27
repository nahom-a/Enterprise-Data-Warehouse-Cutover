CREATE OR REPLACE MACRO clean_string(str_val) AS
    TRIM(LOWER(str_val));
