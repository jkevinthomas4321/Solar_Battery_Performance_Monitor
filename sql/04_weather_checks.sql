-- =============================================================================
-- 04_weather_checks.sql
-- Weather sensor quality: gaps, plausible ranges and frozen values.
-- Irradiation unit: kW/m2.
-- =============================================================================

-- [Q04-A] Missing weather timestamps per plant
WITH grid AS (
    SELECT generate_series(
        TIMESTAMP '2020-05-15 00:00',
        TIMESTAMP '2020-06-17 23:45',
        INTERVAL '15 minutes'
    ) AS date_time
),
plants AS (
    SELECT DISTINCT plant_id FROM weather
)
SELECT
    p.plant_id,
    COUNT(*) AS missing_total,
    COUNT(*) FILTER (WHERE g.date_time::TIME BETWEEN '06:00' AND '18:30') AS missing_daylight
FROM plants AS p
CROSS JOIN grid AS g
LEFT JOIN weather AS w
    ON w.plant_id = p.plant_id
   AND w.date_time = g.date_time
WHERE w.date_time IS NULL
GROUP BY p.plant_id
ORDER BY p.plant_id;

-- [Q04-B] Value ranges and missing irradiation values
SELECT
    plant_id,
    COUNT(*)                      AS n_rows,
    MIN(ambient_temperature)      AS min_ambient,
    MAX(ambient_temperature)      AS max_ambient,
    MIN(module_temperature)       AS min_module,
    MAX(module_temperature)       AS max_module,
    MIN(irradiation)              AS min_irr,
    MAX(irradiation)              AS max_irr,
    COUNT(*) - COUNT(irradiation) AS null_irr
FROM weather
GROUP BY plant_id
ORDER BY plant_id;

-- [Q04-C] Frozen sensor: same non-zero value in three consecutive readings
WITH w AS (
    SELECT
        plant_id,
        date_time,
        module_temperature,
        irradiation,
        LAG(module_temperature)  OVER (PARTITION BY plant_id ORDER BY date_time) AS mt_prev,
        LEAD(module_temperature) OVER (PARTITION BY plant_id ORDER BY date_time) AS mt_next,
        LAG(irradiation)         OVER (PARTITION BY plant_id ORDER BY date_time) AS irr_prev,
        LEAD(irradiation)        OVER (PARTITION BY plant_id ORDER BY date_time) AS irr_next
    FROM weather
)
SELECT
    plant_id,
    COUNT(*) FILTER (
        WHERE module_temperature = mt_prev
          AND module_temperature = mt_next
    ) AS frozen_module_temp,
    COUNT(*) FILTER (
        WHERE irradiation > 0
          AND irradiation = irr_prev
          AND irradiation = irr_next
    ) AS frozen_irradiation
FROM w
GROUP BY plant_id
ORDER BY plant_id;

-- [Q04-D] Generation readings without a matching weather reading
SELECT
    g.plant_id,
    COUNT(*) AS generation_rows_without_weather
FROM generation AS g
LEFT JOIN weather AS w
    ON w.plant_id = g.plant_id
   AND w.date_time = g.date_time
WHERE w.date_time IS NULL
GROUP BY g.plant_id
ORDER BY g.plant_id;
