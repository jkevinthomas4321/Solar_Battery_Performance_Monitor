-- =============================================================================
-- 08_kpis.sql
-- Performance KPIs: daily energy, insolation, performance ratio and rankings.
-- Q08-C to Q08-G read the KPI tables written by src/kpis.py.
-- =============================================================================

-- [Q08-A] Daily energy per plant
SELECT
    plant_id,
    DATE_TRUNC('day', date_time)::DATE AS day,
    ROUND(SUM(energy_kwh)::NUMERIC, 0) AS energy_kwh,
    COUNT(*)                           AS n_readings
FROM generation_clean
GROUP BY plant_id, day
ORDER BY plant_id, day;

-- [Q08-B] Daily insolation per plant (kWh/m2)
SELECT
    plant_id,
    DATE_TRUNC('day', date_time)::DATE           AS day,
    ROUND((SUM(irradiation) * 0.25)::NUMERIC, 2) AS insolation_kwh_m2
FROM weather
GROUP BY plant_id, day
ORDER BY plant_id, day;

-- [Q08-C] Daily plant performance ratio
WITH energy AS (
    SELECT
        plant_id,
        DATE_TRUNC('day', date_time)::DATE AS day,
        SUM(energy_kwh)                    AS energy_kwh,
        COUNT(*)                           AS n_readings
    FROM generation_clean
    GROUP BY plant_id, day
),
sun AS (
    SELECT
        plant_id,
        DATE_TRUNC('day', date_time)::DATE AS day,
        SUM(irradiation) * 0.25            AS insolation_kwh_m2,
        COUNT(*)                           AS n_weather
    FROM weather
    GROUP BY plant_id, day
)
SELECT
    e.plant_id,
    e.day,
    ROUND(e.energy_kwh::NUMERIC, 0)        AS energy_kwh,
    ROUND(s.insolation_kwh_m2::NUMERIC, 2) AS insolation_kwh_m2,
    ROUND((e.energy_kwh / (p.capacity_mwp * 1000 * s.insolation_kwh_m2))::NUMERIC, 3) AS pr,
    (e.n_readings >= 0.9 * 22 * 96 AND s.n_weather >= 0.9 * 96) AS complete_day
FROM energy AS e
JOIN sun AS s
    ON s.plant_id = e.plant_id
   AND s.day = e.day
JOIN kpi_plant AS p
    ON p.plant_id = e.plant_id
ORDER BY e.plant_id, e.day;

-- [Q08-D] Plant comparison
SELECT
    plant_id,
    ROUND(capacity_mwp::NUMERIC, 1)         AS capacity_mwp,
    ROUND(energy_total_mwh::NUMERIC, 0)     AS energy_mwh,
    ROUND((pr * 100)::NUMERIC, 1)           AS pr_pct,
    ROUND((availability * 100)::NUMERIC, 1) AS availability_pct,
    ROUND(downtime_hours::NUMERIC, 0)       AS downtime_hours
FROM kpi_plant
ORDER BY plant_id;

-- [Q08-E] Inverter ranking within each plant by PR and availability
SELECT
    plant_id,
    source_key,
    ROUND((pr * 100)::NUMERIC, 1)                                  AS pr_pct,
    RANK() OVER (PARTITION BY plant_id ORDER BY pr DESC)           AS pr_rank,
    ROUND((availability * 100)::NUMERIC, 1)                        AS availability_pct,
    RANK() OVER (PARTITION BY plant_id ORDER BY availability DESC) AS availability_rank
FROM kpi_inverter
ORDER BY plant_id, pr_rank;

-- [Q08-F] Bottom five inverters per plant by PR
WITH ranked AS (
    SELECT
        plant_id,
        source_key,
        pr,
        availability,
        downtime_hours,
        ROW_NUMBER() OVER (PARTITION BY plant_id ORDER BY pr ASC) AS worst_position
    FROM kpi_inverter
)
SELECT
    plant_id,
    worst_position,
    source_key,
    ROUND((pr * 100)::NUMERIC, 1)           AS pr_pct,
    ROUND((availability * 100)::NUMERIC, 1) AS availability_pct,
    ROUND(downtime_hours::NUMERIC, 1)       AS downtime_hours
FROM ranked
WHERE worst_position <= 5
ORDER BY plant_id, worst_position;

-- [Q08-G] Inverter PR compared with the plant average
SELECT
    plant_id,
    source_key,
    ROUND((pr * 100)::NUMERIC, 1)                                          AS pr_pct,
    ROUND((AVG(pr) OVER (PARTITION BY plant_id) * 100)::NUMERIC, 1)        AS plant_avg_pr_pct,
    ROUND(((pr - AVG(pr) OVER (PARTITION BY plant_id)) * 100)::NUMERIC, 1) AS diff_pct_points
FROM kpi_inverter
ORDER BY diff_pct_points;
