-- 03_missing_timestamps.sql
-- Phase 3, Step 1: find missing 15-minute intervals.
-- Two kinds of gap:
--   plant-wide  = the plant reported nothing at that timestamp (logger / network down)
--   inverter    = the plant reported, but one inverter did not (device or its comms link)
-- Daylight assumption: 06:00-18:30 (local plant time). Night gaps cost no energy.


-- A. Every plant-wide missing timestamp
WITH grid AS (                                   -- the complete expected timeline
    SELECT generate_series(TIMESTAMP '2020-05-15 00:00',
                           TIMESTAMP '2020-06-17 23:45',
                           INTERVAL '15 minutes') AS date_time
),
plants  AS (SELECT DISTINCT plant_id FROM generation),
present AS (SELECT DISTINCT plant_id, date_time FROM generation)
SELECT p.plant_id, g.date_time
FROM plants p
CROSS JOIN grid g                                -- every plant x every expected timestamp
LEFT JOIN present pr
       ON pr.plant_id = p.plant_id AND pr.date_time = g.date_time
WHERE pr.date_time IS NULL                       -- no match = missing
ORDER BY p.plant_id, g.date_time;


-- B. Plant-wide missing intervals per day
WITH grid AS (
    SELECT generate_series(TIMESTAMP '2020-05-15 00:00', TIMESTAMP '2020-06-17 23:45',
                           INTERVAL '15 minutes') AS date_time
),
plants  AS (SELECT DISTINCT plant_id FROM generation),
present AS (SELECT DISTINCT plant_id, date_time FROM generation)
SELECT p.plant_id,
       g.date_time::date AS day,
       COUNT(*)          AS missing_intervals
FROM plants p
CROSS JOIN grid g
LEFT JOIN present pr
       ON pr.plant_id = p.plant_id AND pr.date_time = g.date_time
WHERE pr.date_time IS NULL
GROUP BY p.plant_id, day
ORDER BY p.plant_id, day;


-- C. Plant-wide missing intervals: total, daylight, night
WITH grid AS (
    SELECT generate_series(TIMESTAMP '2020-05-15 00:00', TIMESTAMP '2020-06-17 23:45',
                           INTERVAL '15 minutes') AS date_time
),
plants  AS (SELECT DISTINCT plant_id FROM generation),
present AS (SELECT DISTINCT plant_id, date_time FROM generation),
missing AS (
    SELECT p.plant_id, g.date_time
    FROM plants p
    CROSS JOIN grid g
    LEFT JOIN present pr
           ON pr.plant_id = p.plant_id AND pr.date_time = g.date_time
    WHERE pr.date_time IS NULL
)
SELECT plant_id,
       COUNT(*)                                                         AS missing_total,
       COUNT(*) FILTER (WHERE date_time::time BETWEEN '06:00' AND '18:30') AS missing_daylight,
       COUNT(*) FILTER (WHERE date_time::time NOT BETWEEN '06:00' AND '18:30') AS missing_night
FROM missing
GROUP BY plant_id
ORDER BY plant_id;


-- D. Inverter-level gaps: timestamps where the plant reported but this inverter did not
WITH plant_times AS (SELECT DISTINCT plant_id, date_time FROM generation),
inverters        AS (SELECT DISTINCT plant_id, source_key FROM generation),
expected AS (                                    -- each inverter x each timestamp its plant reported
    SELECT i.plant_id, i.source_key, t.date_time
    FROM inverters i
    JOIN plant_times t ON t.plant_id = i.plant_id
)
SELECT e.plant_id,
       e.source_key,
       COUNT(*)                                                           AS missing_intervals,
       COUNT(*) FILTER (WHERE e.date_time::time BETWEEN '06:00' AND '18:30') AS missing_daylight
FROM expected e
LEFT JOIN generation gen
       ON gen.plant_id = e.plant_id
      AND gen.source_key = e.source_key
      AND gen.date_time = e.date_time
WHERE gen.date_time IS NULL
GROUP BY e.plant_id, e.source_key
ORDER BY missing_intervals DESC;


-- E. Longest gaps per inverter: time between consecutive readings longer than 1 hour
--    LAG(x) = the value of x in the previous row (here: previous reading of the same inverter)
WITH readings AS (
    SELECT plant_id,
           source_key,
           date_time,
           LAG(date_time) OVER (PARTITION BY source_key ORDER BY date_time) AS prev_time
    FROM generation
)
SELECT plant_id,
       source_key,
       prev_time              AS last_reading_before_gap,
       date_time              AS first_reading_after_gap,
       date_time - prev_time  AS gap_length
FROM readings
WHERE date_time - prev_time > INTERVAL '1 hour'
ORDER BY gap_length DESC
LIMIT 20;
