# Loads the solar generation and weather CSVs into PostgreSQL
import pandas as pd
from pathlib import Path
from db import engine   # reuses the engine from src/db.py
from sqlalchemy import text

root = Path(__file__).resolve().parent.parent   # src/ → repo root
solar_data = root / "data" / "raw" / "solar"


# file name, table, timestamp format
files = [
    ("Plant_1_Generation_Data.csv",     "generation", "%d-%m-%Y %H:%M"),
    ("Plant_2_Generation_Data.csv",     "generation", "%Y-%m-%d %H:%M:%S"),
    ("Plant_1_Weather_Sensor_Data.csv", "weather", "%Y-%m-%d %H:%M:%S"),
    ("Plant_2_Weather_Sensor_Data.csv", "weather", "%Y-%m-%d %H:%M:%S"),
]

with engine.begin() as conn:
    conn.execute(text("TRUNCATE TABLE generation, weather;")) # committed here automatically with .begin()

for filename, table, fmt in files:
    df = pd.read_csv(solar_data / filename)
    df.columns = df.columns.str.lower()               # to match the lowercase table columns in db table
    df["date_time"] = pd.to_datetime(df["date_time"], format=fmt)
    df.to_sql(table, engine, if_exists="append", index=False)  #loading the df to db
    print(f"{filename}: {len(df)} rows loaded into {table}")