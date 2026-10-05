-- =============================================================================
-- 01_create_tables.sql
-- Raw data tables for inverter generation and plant weather readings.
-- =============================================================================

-- [Q01-A] Inverter generation readings (15-minute intervals)
CREATE TABLE IF NOT EXISTS generation (
    date_time    TIMESTAMP        NOT NULL,
    plant_id     INTEGER          NOT NULL,
    source_key   VARCHAR(15)      NOT NULL,
    dc_power     DOUBLE PRECISION,
    ac_power     DOUBLE PRECISION,
    daily_yield  DOUBLE PRECISION,
    total_yield  DOUBLE PRECISION,
    CONSTRAINT generation_pkey PRIMARY KEY (date_time, plant_id, source_key)
);

-- [Q01-B] Plant weather sensor readings (one sensor per plant)
CREATE TABLE IF NOT EXISTS weather (
    date_time            TIMESTAMP        NOT NULL,
    plant_id             INTEGER          NOT NULL,
    source_key           VARCHAR(15)      NOT NULL,
    ambient_temperature  DOUBLE PRECISION,
    module_temperature   DOUBLE PRECISION,
    irradiation          DOUBLE PRECISION,
    CONSTRAINT weather_pkey PRIMARY KEY (date_time, plant_id)
);
