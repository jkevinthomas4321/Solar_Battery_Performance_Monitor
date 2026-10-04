-- Table creation for the solar power generation and weather data

-- DROP TABLE IF EXISTS public.generation;

CREATE TABLE IF NOT EXISTS public.generation
(
    date_time timestamp without time zone NOT NULL,
    plant_id integer NOT NULL,
    source_key character varying(15) COLLATE pg_catalog."default" NOT NULL,
    dc_power double precision,
    ac_power double precision,
    daily_yield double precision,
    total_yield double precision,
    CONSTRAINT generation_pkey PRIMARY KEY (date_time, plant_id, source_key)
);

-- DROP TABLE IF EXISTS public.weather;

CREATE TABLE IF NOT EXISTS public.weather
(
    date_time timestamp without time zone NOT NULL,
    plant_id integer NOT NULL,
    source_key character varying(15) COLLATE pg_catalog."default" NOT NULL,
    ambient_temperature double precision,
    module_temperature double precision,
    irradiation double precision,
    CONSTRAINT weather_data_pkey PRIMARY KEY (date_time, plant_id)
)


