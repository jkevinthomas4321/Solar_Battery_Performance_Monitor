-- 07_counter_checks.sql
-- Phase 3, Step 5: cumulative energy counters.
-- total_yield = lifetime energy counter (kWh): must never decrease.
-- daily_yield = energy since midnight (kWh): must only rise during the day and reset once per day.


-- A. total_yield going down, or dropping to 0 (counter faults)
WITH c AS (
    SELECT plant_id, source_key, date_time, total_yield,
           LAG(total_yield) OVER (PARTITION BY source_key ORDER BY date_time) AS prev_total
    FROM generation
)
SELECT plant_id,
       COUNT(*) FILTER (WHERE total_yield < prev_total)                 AS total_decreases,
       COUNT(DISTINCT source_key) FILTER (WHERE total_yield < prev_total) AS inverters_affected,
       COUNT(*) FILTER (WHERE total_yield = 0)                          AS total_is_zero,
       ROUND(MAX(total_yield)::numeric, 0)                              AS max_total_kwh
FROM c
GROUP BY plant_id
ORDER BY plant_id;


-- B. daily_yield dropping within the same day (it should only rise until the reset)
WITH c AS (
    SELECT plant_id, source_key, date_time, daily_yield,
           LAG(daily_yield) OVER (PARTITION BY source_key, date_time::date ORDER BY date_time) AS prev_daily
    FROM generation
)
SELECT plant_id,
       COUNT(*) FILTER (WHERE daily_yield < prev_daily) AS daily_drops,
       COUNT(*) FILTER (WHERE daily_yield < prev_daily
                          AND date_time::time BETWEEN '06:00' AND '18:30') AS daily_drops_in_daylight
FROM c
GROUP BY plant_id
ORDER BY plant_id;


-- C. Cross-check: energy from integrating AC power vs the daily_yield counter (median inverter-day)
--    Energy (kWh) = power (kW) x 0.25 h for each 15-minute reading
WITH per_day AS (
    SELECT plant_id, source_key, date_time::date AS day,
           SUM(ac_power) * 0.25 AS ac_energy_kwh,
           MAX(daily_yield)     AS daily_yield_max
    FROM generation
    GROUP BY plant_id, source_key, day
)
SELECT plant_id,
       ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY ac_energy_kwh)::numeric, 0)   AS median_ac_energy_kwh,
       ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY daily_yield_max)::numeric, 0) AS median_daily_yield_kwh
FROM per_day
GROUP BY plant_id
ORDER BY plant_id;


-- D. The four silent Plant 2 inverters: did the counter keep rising during their gap?
--    If total_yield after the gap is higher than before, the inverter kept producing
--    and only the data transmission failed.
WITH readings AS (
    SELECT source_key, date_time, total_yield,
           LAG(date_time)   OVER (PARTITION BY source_key ORDER BY date_time) AS prev_time,
           LAG(total_yield) OVER (PARTITION BY source_key ORDER BY date_time) AS prev_total
    FROM generation
    WHERE plant_id = 4136001
)
SELECT source_key,
       prev_time                        AS gap_start,
       date_time                        AS gap_end,
       date_time - prev_time            AS gap_length,
       ROUND((total_yield - prev_total)::numeric, 0) AS counter_increase_kwh
FROM readings
WHERE date_time - prev_time > INTERVAL '1 day'
ORDER BY source_key;


-- E. Reference: energy a healthy neighbour inverter produced over the same period
--    (integrated from AC power, because Plant 2's total_yield counter has faults - see query A)
SELECT source_key,
       ROUND((SUM(ac_power) * 0.25)::numeric, 0) AS ac_energy_kwh
FROM generation
WHERE plant_id = 4136001
  AND source_key = '4UPUqMRk7TRMgml'
  AND date_time > '2020-05-20 21:45' AND date_time < '2020-05-29 16:15'
GROUP BY source_key;
