-- =============================================================================
-- 06_dc_ac_check.sql
-- DC/AC consistency. Physically expected AC/DC ratio: 0.95-0.99.
-- =============================================================================

-- [Q06-A] AC/DC ratio distribution per plant while producing
SELECT
    plant_id,
    COUNT(*) AS n_rows,
    ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY ac_power / dc_power)::NUMERIC, 4) AS median_ratio,
    ROUND(PERCENTILE_CONT(0.05) WITHIN GROUP (ORDER BY ac_power / dc_power)::NUMERIC, 4) AS p05_ratio,
    ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY ac_power / dc_power)::NUMERIC, 4) AS p95_ratio,
    ROUND(MAX(dc_power)::NUMERIC, 1) AS max_dc,
    ROUND(MAX(ac_power)::NUMERIC, 1) AS max_ac
FROM generation
WHERE dc_power > 0
GROUP BY plant_id
ORDER BY plant_id;

-- [Q06-B] Mean AC/DC ratio per inverter
SELECT
    plant_id,
    source_key,
    ROUND(AVG(ac_power / dc_power)::NUMERIC, 4) AS mean_ratio
FROM generation
WHERE dc_power > 0
GROUP BY plant_id, source_key
ORDER BY plant_id, mean_ratio;

-- [Q06-C] Plant 1 AC/DC ratio after dividing DC power by 10
SELECT
    plant_id,
    ROUND(
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ac_power / (dc_power / 10))::NUMERIC, 4
    ) AS median_ratio_after_fix
FROM generation
WHERE dc_power > 0
  AND plant_id = 4135001
GROUP BY plant_id;
