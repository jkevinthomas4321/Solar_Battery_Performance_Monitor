-- 05_impossible_values.sql
-- Phase 3, Step 3: physically impossible or suspicious values.


-- A. Negative values (power and energy can never be negative)
SELECT plant_id,
       COUNT(*) FILTER (WHERE dc_power    < 0) AS neg_dc,
       COUNT(*) FILTER (WHERE ac_power    < 0) AS neg_ac,
       COUNT(*) FILTER (WHERE daily_yield < 0) AS neg_daily,
       COUNT(*) FILTER (WHERE total_yield < 0) AS neg_total
FROM generation
GROUP BY plant_id
ORDER BY plant_id;


-- B. Power while the irradiation sensor reads zero (no sun -> no power)
SELECT g.plant_id,
       EXTRACT(HOUR FROM g.date_time) AS hour,
       COUNT(*)                        AS n_rows,
       ROUND(MAX(g.ac_power)::numeric, 1) AS max_ac_kw
FROM generation g
JOIN weather w ON w.plant_id = g.plant_id AND w.date_time = g.date_time
WHERE w.irradiation = 0 AND g.ac_power > 0
GROUP BY g.plant_id, hour
ORDER BY g.plant_id, hour;


-- C. Zero output in good sun (irradiation > 0.2 kW/m2): per inverter
--    Not a data error by itself: this is where real downtime shows up. Flag, don't delete.
SELECT g.plant_id,
       g.source_key,
       COUNT(*)                     AS zero_output_intervals,
       ROUND(COUNT(*) / 4.0, 1)     AS zero_output_hours
FROM generation g
JOIN weather w ON w.plant_id = g.plant_id AND w.date_time = g.date_time
WHERE w.irradiation > 0.2 AND g.ac_power = 0
GROUP BY g.plant_id, g.source_key
ORDER BY zero_output_intervals DESC;


-- D. Same as C, summarised per plant
SELECT g.plant_id,
       COUNT(*)                  AS zero_output_intervals,
       COUNT(DISTINCT g.source_key) AS inverters_affected
FROM generation g
JOIN weather w ON w.plant_id = g.plant_id AND w.date_time = g.date_time
WHERE w.irradiation > 0.2 AND g.ac_power = 0
GROUP BY g.plant_id
ORDER BY g.plant_id;
