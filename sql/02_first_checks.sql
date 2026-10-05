-- Checks the Rows per plant, time range and inverter count per plant
/*
SELECT plant_id,
	COUNT(*) AS n_rows,
	MIN(date_time) AS first_reading,
	MAX(date_time) AS last_reading,
	COUNT(DISTINCT source_key) AS n_inverters
FROM generation
GROUP BY plant_id
ORDER BY plant_id;


-- Checks the inverter count and rows per inverter for each plant 
SELECT source_key,
	COUNT(*) AS n_rows
FROM generation
WHERE plant_id = 4135001
GROUP BY source_key
ORDER BY n_rows ASC;
*/

SELECT plant_id,
	COUNT(*) AS n_rows,
	MIN(date_time) AS first_reading,
	MAX(date_time) AS last_reading,
	COUNT(DISTINCT source_key) AS n_sensors,
	3264 - COUNT(*)            AS missing_intervals
FROM weather
GROUP BY plant_id
ORDER BY plant_id;