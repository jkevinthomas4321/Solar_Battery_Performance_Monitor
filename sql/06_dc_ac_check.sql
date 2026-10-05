-- 06_dc_ac_check.sql
-- Phase 3, Step 4: DC vs AC consistency.
-- An inverter converts DC to AC with about 95-99 % efficiency, so AC/DC must be close to 1
-- and AC can never exceed DC.


-- A. AC/DC ratio per plant (only when the inverter is producing)
SELECT plant_id,
       COUNT(*) AS n_rows,
       ROUND(percentile_cont(0.5)  WITHIN GROUP (ORDER BY ac_power / dc_power)::numeric, 4) AS median_ratio,
       ROUND(percentile_cont(0.05) WITHIN GROUP (ORDER BY ac_power / dc_power)::numeric, 4) AS p05_ratio,
       ROUND(percentile_cont(0.95) WITHIN GROUP (ORDER BY ac_power / dc_power)::numeric, 4) AS p95_ratio,
       ROUND(MAX(dc_power)::numeric, 1) AS max_dc,
       ROUND(MAX(ac_power)::numeric, 1) AS max_ac
FROM generation
WHERE dc_power > 0
GROUP BY plant_id
ORDER BY plant_id;


-- B. Is the Plant 1 problem in every inverter or only some? (ratio per inverter)
SELECT plant_id,
       source_key,
       ROUND(AVG(ac_power / dc_power)::numeric, 4) AS mean_ratio
FROM generation
WHERE dc_power > 0
GROUP BY plant_id, source_key
ORDER BY plant_id, mean_ratio;


-- C. Check of the fix: Plant 1 ratio after dividing DC by 10
SELECT plant_id,
       ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY ac_power / (dc_power / 10))::numeric, 4) AS median_ratio_after_fix
FROM generation
WHERE dc_power > 0 AND plant_id = 4135001
GROUP BY plant_id;
