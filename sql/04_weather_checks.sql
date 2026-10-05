-- 04_weather_checks.sql
-- Phase 3, Step 2: weather sensor quality (gaps, plausible ranges, frozen sensors).
-- Note: IRRADIATION is in kW/m2 (1.0 = 1000 W/m2, roughly full sun).


-- A. Missing weather timestamps per plant (expected 3,264 per plant)
WITH grid AS (
    SELECT generate_series(TIMESTAMP '2020-05-15 00:00', TIMESTAMP '2020-06-17 23:45',
                           INTERVAL '15 minutes') AS date_time
),
plants AS (SELECT DISTINCT plant_id FROM weather)
SELECT p.plant_id,
       COUNT(*)                                                           AS missing_total,
       COUNT(*) FILTER (WHERE g.date_time::time BETWEEN '06:00' AND '18:30') AS missing_daylight
FROM plants p
CROSS JOIN grid g
LEFT JOIN weather w ON w.plant_id = p.plant_id AND w.date_time = g.date_time
WHERE w.date_time IS NULL
GROUP BY p.plant_id
ORDER BY p.plant_id;


-- B. Value ranges: are all readings physically plausible?
--    Expected: ambient 15-45 C, module 15-75 C, irradiation 0-1.4 kW/m2, no NULLs
SELECT plant_id,
       COUNT(*)                                   AS n_rows,
       MIN(ambient_temperature)                   AS min_ambient,
       MAX(ambient_temperature)                   AS max_ambient,
       MIN(module_temperature)                    AS min_module,
       MAX(module_temperature)                    AS max_module,
       MIN(irradiation)                           AS min_irr,
       MAX(irradiation)                           AS max_irr,
       COUNT(*) - COUNT(irradiation)              AS null_irr
FROM weather
GROUP BY plant_id
ORDER BY plant_id;


-- C. Frozen sensor: the same non-zero value three readings in a row
--    A live sensor's decimal readings practically never repeat exactly.
WITH w AS (
    SELECT plant_id, date_time, module_temperature, irradiation,
           LAG(module_temperature)  OVER (PARTITION BY plant_id ORDER BY date_time) AS mt_prev,
           LEAD(module_temperature) OVER (PARTITION BY plant_id ORDER BY date_time) AS mt_next,
           LAG(irradiation)         OVER (PARTITION BY plant_id ORDER BY date_time) AS irr_prev,
           LEAD(irradiation)        OVER (PARTITION BY plant_id ORDER BY date_time) AS irr_next
    FROM weather
)
SELECT plant_id,
       COUNT(*) FILTER (WHERE module_temperature = mt_prev AND module_temperature = mt_next) AS frozen_module_temp,
       COUNT(*) FILTER (WHERE irradiation > 0 AND irradiation = irr_prev AND irradiation = irr_next) AS frozen_irradiation
FROM w
GROUP BY plant_id
ORDER BY plant_id;


-- D. Generation rows with no matching weather reading (these cannot get an expected value later)
SELECT g.plant_id,
       COUNT(*) AS generation_rows_without_weather
FROM generation g
LEFT JOIN weather w ON w.plant_id = g.plant_id AND w.date_time = g.date_time
WHERE w.date_time IS NULL
GROUP BY g.plant_id
ORDER BY g.plant_id;
