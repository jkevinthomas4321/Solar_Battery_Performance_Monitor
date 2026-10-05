-- =============================================================================
-- 07_counter_checks.sql
-- Energy counter integrity (total_yield, daily_yield) and the Plant 2 gap check.
-- =============================================================================

-- [Q07-A] total_yield decreases and zero values per plant
WITH c AS (
    SELECT
        plant_id,
        source_key,
        date_time,
        total_yield,
        LAG(total_yield) OVER (PARTITION BY source_key ORDER BY date_time) AS prev_total
    FROM generation
)
SELECT
    plant_id,
    COUNT(*) FILTER (WHERE total_yield < prev_total)                   AS total_decreases,
    COUNT(DISTINCT source_key) FILTER (WHERE total_yield < prev_total) AS inverters_affected,
    COUNT(*) FILTER (WHERE total_yield = 0)                            AS total_is_zero,
    ROUND(MAX(total_yield)::NUMERIC, 0)                                AS max_total_kwh
FROM c
GROUP BY plant_id
ORDER BY plant_id;

-- [Q07-B] daily_yield drops within the same day
WITH c AS (
    SELECT
        plant_id,
        source_key,
        date_time,
        daily_yield,
        LAG(daily_yield) OVER (
            PARTITION BY source_key, date_time::DATE
            ORDER BY date_time
        ) AS prev_daily
    FROM generation
)
SELECT
    plant_id,
    COUNT(*) FILTER (WHERE daily_yield < prev_daily) AS daily_drops,
    COUNT(*) FILTER (
        WHERE daily_yield < prev_daily
          AND date_time::TIME BETWEEN '06:00' AND '18:30'
    ) AS daily_drops_in_daylight
FROM c
GROUP BY plant_id
ORDER BY plant_id;

-- [Q07-C] Median inverter-day energy: integrated AC power vs daily_yield counter
WITH per_day AS (
    SELECT
        plant_id,
        source_key,
        date_time::DATE      AS day,
        SUM(ac_power) * 0.25 AS ac_energy_kwh,
        MAX(daily_yield)     AS daily_yield_max
    FROM generation
    GROUP BY plant_id, source_key, day
)
SELECT
    plant_id,
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ac_energy_kwh)::NUMERIC, 0)   AS median_ac_energy_kwh,
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY daily_yield_max)::NUMERIC, 0) AS median_daily_yield_kwh
FROM per_day
GROUP BY plant_id
ORDER BY plant_id;

-- [Q07-D] Plant 2 gaps longer than one day and the counter increase across each gap
WITH readings AS (
    SELECT
        source_key,
        date_time,
        total_yield,
        LAG(date_time)   OVER (PARTITION BY source_key ORDER BY date_time) AS prev_time,
        LAG(total_yield) OVER (PARTITION BY source_key ORDER BY date_time) AS prev_total
    FROM generation
    WHERE plant_id = 4136001
)
SELECT
    source_key,
    prev_time                                     AS gap_start,
    date_time                                     AS gap_end,
    date_time - prev_time                         AS gap_length,
    ROUND((total_yield - prev_total)::NUMERIC, 0) AS counter_increase_kwh
FROM readings
WHERE date_time - prev_time > INTERVAL '1 day'
ORDER BY source_key;

-- [Q07-E] Reference energy of a healthy Plant 2 inverter over the same period
SELECT
    source_key,
    ROUND((SUM(ac_power) * 0.25)::NUMERIC, 0) AS ac_energy_kwh
FROM generation
WHERE plant_id = 4136001
  AND source_key = '4UPUqMRk7TRMgml'
  AND date_time > '2020-05-20 21:45'
  AND date_time < '2020-05-29 16:15'
GROUP BY source_key;
