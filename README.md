# Solar + Battery Performance Monitor

Performance analysis of two utility-scale PV plants and a set of Li-ion battery cells using real operating and test data. The project covers data loading, validation, KPIs, physics-based expected output, loss quantification in kWh and EUR, thermal effects, root-cause diagnosis and battery health.

> **Status:** work in progress, Phase 1 (setup) complete.

## Data

The raw data is **not included in this repository** (it is excluded via `.gitignore`). Download it from the links below and place it in the folders shown.

### 1. Solar: Solar Power Generation Data

| | |
|---|---|
| Source | [Kaggle: Solar Power Generation Data](https://www.kaggle.com/datasets/anikannal/solar-power-generation-data) |
| Author | anikannal |
| Content | Two PV plants in India, inverter-level generation data and plant-level weather sensor data |
| Period | 15 May 2020 – 17 June 2020 (34 days) at 15-minute intervals |
| Location in repo | `data/raw/solar/` |

| File | Rows | Description |
|---|---:|---|
| `Plant_1_Generation_Data.csv` | 68,778 | 22 inverters: `DATE_TIME`, `PLANT_ID`, `SOURCE_KEY` (inverter ID), `DC_POWER`, `AC_POWER`, `DAILY_YIELD`, `TOTAL_YIELD` |
| `Plant_1_Weather_Sensor_Data.csv` | 3,182 | 1 sensor: `DATE_TIME`, `PLANT_ID`, `SOURCE_KEY`, `AMBIENT_TEMPERATURE`, `MODULE_TEMPERATURE`, `IRRADIATION` |
| `Plant_2_Generation_Data.csv` | 67,698 | 22 inverters, same columns as Plant 1 |
| `Plant_2_Weather_Sensor_Data.csv` | 3,259 | 1 sensor, same columns as Plant 1 |

### 2. Battery: NASA Li-ion Battery Aging Dataset

| | |
|---|---|
| Source | [Kaggle: NASA Battery Dataset](https://www.kaggle.com/datasets/patrickfleith/nasa-battery-dataset) (author: Patrick Fleith) |
| Original data | NASA Ames Prognostics Center of Excellence (PCoE), *Li-ion Battery Aging Datasets*, B. Saha and K. Goebel (2007), [NASA Open Data Portal](https://data.nasa.gov/) |
| Content | CSV conversion of the original MATLAB `.mat` files: 34 cells (B0005 – B0056) cycled through charge, discharge and impedance (EIS) tests at ambient temperatures of 4, 22, 24, 43 and 44 °C until end-of-life |
| Location in repo | `data/raw/battery/cleaned_dataset/` |

| Item | Description |
|---|---|
| `metadata.csv` | One row per test (7,565 rows): `type` (charge / discharge / impedance), `start_time`, `ambient_temperature`, `battery_id`, `test_id`, `uid`, `filename`, `Capacity` (Ah, discharge tests), `Re`, `Rct` (Ω, impedance tests) |
| `data/` | One CSV per test with the measured time series (voltage, current, temperature, time) |
| `extra_infos/` | Original NASA README files describing the test conditions for each group of cells |

Test counts: 2,815 charge, 2,794 discharge and 1,956 impedance tests.

## Repository structure

```
data/raw/         original data, read-only, not tracked by Git
data/processed/   cleaned data produced by the scripts, not tracked by Git
sql/              SQL queries, each with a comment explaining its purpose
src/              Python modules (database connection, loading, validation, KPIs, ...)
notebooks/        exploratory analysis
reports/          data-quality and diagnosis reports
dashboard/        Power BI dashboard and screenshots
```

## Setup

1. Create and activate a virtual environment, then install the dependencies:
   ```
   python -m venv solar_env
   solar_env\Scripts\activate
   pip install -r requirements.txt
   ```
2. Install PostgreSQL and create a database named `solar_monitor`.
3. Copy `.env.example` to `.env` and fill in your database credentials.
4. Test the connection: `python src/db.py`
5. Download both datasets into `data/raw/` as described above.

## Tools

Python (pandas, NumPy, SciPy, scikit-learn, pvlib), PostgreSQL, SQLAlchemy, DuckDB, Power BI, Git.
