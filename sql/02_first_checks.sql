-- =============================================================================
-- 02_first_checks.sql
-- Post-load smoke tests: row counts, time ranges and devices per plant.
-- Expected per device: 34 days x 96 intervals = 3,264 readings.
-- =============================================================================

-- [Q02-A] Generation: rows, time range and inverters per plant
SELECT
    plant_id,
    COUNT(*)                   AS n_rows,
    MIN(date_time)             AS first_reading,
    MAX(date_time)             AS last_reading,
    COUNT(DISTINCT source_key) AS n_inverters
FROM generation
GROUP BY plant_id
ORDER BY plant_id;

-- [Q02-B] Generation: readings per inverter, fewest first
SELECT
    plant_id,
    source_key,
    COUNT(*)        AS n_rows,
    3264 - COUNT(*) AS missing_intervals
FROM generation
GROUP BY plant_id, source_key
ORDER BY plant_id, n_rows;

-- [Q02-C] Weather: rows, time range and sensors per plant
SELECT
    plant_id,
    COUNT(*)                   AS n_rows,
    MIN(date_time)             AS first_reading,
    MAX(date_time)             AS last_reading,
    COUNT(DISTINCT source_key) AS n_sensors,
    3264 - COUNT(*)            AS missing_intervals
FROM weather
GROUP BY plant_id
ORDER BY plant_id;
