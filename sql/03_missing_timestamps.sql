-- =============================================================================
-- 03_missing_timestamps.sql
-- Missing 15-minute intervals at plant level and inverter level.
-- Daylight window: 06:00-18:30.
-- =============================================================================

-- [Q03-A] Plant-wide missing timestamps
WITH grid AS (
    SELECT generate_series(
        TIMESTAMP '2020-05-15 00:00',
        TIMESTAMP '2020-06-17 23:45',
        INTERVAL '15 minutes'
    ) AS date_time
),
plants AS (
    SELECT DISTINCT plant_id FROM generation
),
present AS (
    SELECT DISTINCT plant_id, date_time FROM generation
)
SELECT
    p.plant_id,
    g.date_time
FROM plants AS p
CROSS JOIN grid AS g
LEFT JOIN present AS pr
    ON pr.plant_id = p.plant_id
   AND pr.date_time = g.date_time
WHERE pr.date_time IS NULL
ORDER BY p.plant_id, g.date_time;

-- [Q03-B] Plant-wide missing intervals per day
WITH grid AS (
    SELECT generate_series(
        TIMESTAMP '2020-05-15 00:00',
        TIMESTAMP '2020-06-17 23:45',
        INTERVAL '15 minutes'
    ) AS date_time
),
plants AS (
    SELECT DISTINCT plant_id FROM generation
),
present AS (
    SELECT DISTINCT plant_id, date_time FROM generation
)
SELECT
    p.plant_id,
    g.date_time::DATE AS day,
    COUNT(*)          AS missing_intervals
FROM plants AS p
CROSS JOIN grid AS g
LEFT JOIN present AS pr
    ON pr.plant_id = p.plant_id
   AND pr.date_time = g.date_time
WHERE pr.date_time IS NULL
GROUP BY p.plant_id, day
ORDER BY p.plant_id, day;

-- [Q03-C] Plant-wide missing intervals split into daylight and night
WITH grid AS (
    SELECT generate_series(
        TIMESTAMP '2020-05-15 00:00',
        TIMESTAMP '2020-06-17 23:45',
        INTERVAL '15 minutes'
    ) AS date_time
),
plants AS (
    SELECT DISTINCT plant_id FROM generation
),
present AS (
    SELECT DISTINCT plant_id, date_time FROM generation
),
missing AS (
    SELECT
        p.plant_id,
        g.date_time
    FROM plants AS p
    CROSS JOIN grid AS g
    LEFT JOIN present AS pr
        ON pr.plant_id = p.plant_id
       AND pr.date_time = g.date_time
    WHERE pr.date_time IS NULL
)
SELECT
    plant_id,
    COUNT(*) AS missing_total,
    COUNT(*) FILTER (WHERE date_time::TIME BETWEEN '06:00' AND '18:30')     AS missing_daylight,
    COUNT(*) FILTER (WHERE date_time::TIME NOT BETWEEN '06:00' AND '18:30') AS missing_night
FROM missing
GROUP BY plant_id
ORDER BY plant_id;

-- [Q03-D] Inverter-level missing intervals (plant reported, inverter did not)
WITH plant_times AS (
    SELECT DISTINCT plant_id, date_time FROM generation
),
inverters AS (
    SELECT DISTINCT plant_id, source_key FROM generation
),
expected AS (
    SELECT
        i.plant_id,
        i.source_key,
        t.date_time
    FROM inverters AS i
    JOIN plant_times AS t
        ON t.plant_id = i.plant_id
)
SELECT
    e.plant_id,
    e.source_key,
    COUNT(*) AS missing_intervals,
    COUNT(*) FILTER (WHERE e.date_time::TIME BETWEEN '06:00' AND '18:30') AS missing_daylight
FROM expected AS e
LEFT JOIN generation AS gen
    ON gen.plant_id = e.plant_id
   AND gen.source_key = e.source_key
   AND gen.date_time = e.date_time
WHERE gen.date_time IS NULL
GROUP BY e.plant_id, e.source_key
ORDER BY missing_intervals DESC;

-- [Q03-E] Longest gaps between consecutive readings of an inverter (> 1 hour)
WITH readings AS (
    SELECT
        plant_id,
        source_key,
        date_time,
        LAG(date_time) OVER (PARTITION BY source_key ORDER BY date_time) AS prev_time
    FROM generation
)
SELECT
    plant_id,
    source_key,
    prev_time             AS last_reading_before_gap,
    date_time             AS first_reading_after_gap,
    date_time - prev_time AS gap_length
FROM readings
WHERE date_time - prev_time > INTERVAL '1 hour'
ORDER BY gap_length DESC
LIMIT 20;
