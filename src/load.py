"""Load the raw solar generation and weather CSV files into PostgreSQL.

The target tables are emptied first, so the load can be rerun safely.

Usage:
    python src/load.py
"""

import pandas as pd
from sqlalchemy import text

from config import RAW_SOLAR_DIR
from db import get_engine

SOURCE_FILES = [
    ("Plant_1_Generation_Data.csv", "generation", "%d-%m-%Y %H:%M"),
    ("Plant_2_Generation_Data.csv", "generation", "%Y-%m-%d %H:%M:%S"),
    ("Plant_1_Weather_Sensor_Data.csv", "weather", "%Y-%m-%d %H:%M:%S"),
    ("Plant_2_Weather_Sensor_Data.csv", "weather", "%Y-%m-%d %H:%M:%S"),
]


def read_source_file(filename: str, timestamp_format: str) -> pd.DataFrame:
    """Read one CSV, lower-case its columns and parse timestamps explicitly.

    Args:
        filename: CSV file name inside data/raw/solar.
        timestamp_format: strftime format of the DATE_TIME column in this file.

    Returns:
        DataFrame with column names matching the database tables.
    """
    df = pd.read_csv(RAW_SOLAR_DIR / filename)
    df.columns = df.columns.str.lower()
    df["date_time"] = pd.to_datetime(df["date_time"], format=timestamp_format)
    return df


def truncate_tables(tables: list[str]) -> None:
    """Remove all rows from the given tables while keeping their structure."""
    with get_engine().begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE {', '.join(tables)};"))


def load_all() -> None:
    """Empty the target tables and load every source file."""
    truncate_tables(sorted({table for _, table, _ in SOURCE_FILES}))
    for filename, table, timestamp_format in SOURCE_FILES:
        df = read_source_file(filename, timestamp_format)
        df.to_sql(table, get_engine(), if_exists="append", index=False)
        print(f"{filename}: {len(df):,} rows loaded into {table}")


if __name__ == "__main__":
    load_all()
