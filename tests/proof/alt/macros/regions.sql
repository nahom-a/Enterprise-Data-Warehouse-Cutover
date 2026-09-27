CREATE OR REPLACE MACRO default_region(reg) AS
    COALESCE(reg, 'UNKNOWN');
