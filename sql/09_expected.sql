-- =============================================================================
-- 09_expected.sql
-- Expected performance: model accuracy, losses by category, sustained underperformance.
-- Reads the tables written by src/expected.py.
-- =============================================================================

-- [Q09-A] Model accuracy on unseen healthy days: physics model vs regression
SELECT
    plant_id,
    model,
    n_test,
    ROUND(mae_kw::NUMERIC, 1)          AS mae_kw,
    ROUND((nmae * 100)::NUMERIC, 1)    AS nmae_pct,
    ROUND(bias_kw::NUMERIC, 1)         AS bias_kw,
    ROUND(r2::NUMERIC, 3)              AS r2,
    ROUND(gamma_estimate::NUMERIC, 4)  AS gamma_per_degc
FROM model_validation
ORDER BY plant_id, model;

-- [Q09-B] Share of sunny intervals per category and plant
SELECT
    plant_id,
    category,
    COUNT(*)                                                                    AS intervals,
    ROUND((100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY plant_id))::NUMERIC, 2) AS share_pct
FROM expected_power
GROUP BY plant_id, category
ORDER BY plant_id, intervals DESC;

-- [Q09-C] Expected vs actual energy and losses by category per plant (MWh)
SELECT
    plant_id,
    ROUND(SUM(expected_mwh)::NUMERIC, 0)         AS expected_mwh,
    ROUND(SUM(actual_mwh)::NUMERIC, 0)           AS actual_mwh,
    ROUND(SUM(downtime_loss_mwh)::NUMERIC, 1)    AS downtime_mwh,
    ROUND(SUM(underperformance_mwh)::NUMERIC, 1) AS underperformance_mwh,
    ROUND(SUM(clipping_loss_mwh)::NUMERIC, 1)    AS clipping_mwh,
    ROUND(SUM(total_loss_mwh)::NUMERIC, 1)       AS total_loss_mwh,
    ROUND((100 * SUM(total_loss_mwh) / SUM(expected_mwh))::NUMERIC, 1) AS loss_pct_of_expected
FROM expected_inverter
GROUP BY plant_id
ORDER BY plant_id;

-- [Q09-D] Inverters ranked by total loss within each plant
SELECT
    plant_id,
    RANK() OVER (PARTITION BY plant_id ORDER BY total_loss_mwh DESC) AS loss_rank,
    source_key,
    ROUND(total_loss_mwh::NUMERIC, 1)       AS total_loss_mwh,
    ROUND(downtime_loss_mwh::NUMERIC, 1)    AS downtime_mwh,
    ROUND(underperformance_mwh::NUMERIC, 1) AS underperformance_mwh,
    ROUND(median_pi_running::NUMERIC, 3)    AS median_pi_running,
    sustained_days
FROM expected_inverter
ORDER BY plant_id, loss_rank;

-- [Q09-E] Daily plant performance index (complete inverter-days only)
SELECT
    plant_id,
    day::DATE                                             AS day,
    ROUND((SUM(actual_kwh) / SUM(expected_kwh))::NUMERIC, 3) AS performance_index,
    ROUND(SUM(downtime_loss_kwh)::NUMERIC, 0)             AS downtime_kwh,
    COUNT(*)                                              AS inverters
FROM expected_daily
WHERE complete
GROUP BY plant_id, day
ORDER BY plant_id, day;

-- [Q09-F] Sustained underperformance periods (gaps-and-islands on low-PI days)
WITH low_days AS (
    SELECT
        plant_id,
        source_key,
        day::DATE AS day,
        day::DATE - (ROW_NUMBER() OVER (PARTITION BY source_key ORDER BY day))::INTEGER AS island
    FROM expected_daily
    WHERE sustained_underperformance
)
SELECT
    plant_id,
    source_key,
    MIN(day)  AS period_start,
    MAX(day)  AS period_end,
    COUNT(*)  AS low_pi_days
FROM low_days
GROUP BY plant_id, source_key, island
ORDER BY low_pi_days DESC, plant_id, source_key;
