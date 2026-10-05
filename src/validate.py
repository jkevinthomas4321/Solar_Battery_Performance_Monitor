"""Apply the data-quality decisions and build clean tables for the KPI phases.

Reads the raw tables ``generation`` and ``weather`` (never modified) and writes:

* ``generation_clean``: every reading with corrected DC power, energy per
  interval and quality flags.
* ``data_gaps``: one row per gap event (consecutive missing 15-minute
  intervals of one inverter) with its classification.

Usage:
    python src/validate.py
"""

import pandas as pd
from sqlalchemy import text

from config import (
    DAYLIGHT_END,
    DAYLIGHT_START,
    DC_SCALE_FACTOR,
    INTERVAL_H,
    SUN_THRESHOLD_ZERO_OUTPUT,
)
from db import get_engine


def load_raw() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read the raw generation and weather tables from PostgreSQL."""
    engine = get_engine()
    generation = pd.read_sql("SELECT * FROM generation", engine)
    weather = pd.read_sql(
        "SELECT plant_id, date_time, ambient_temperature, module_temperature, irradiation "
        "FROM weather",
        engine,
    )
    generation = generation.sort_values(["source_key", "date_time"]).reset_index(drop=True)
    return generation, weather


def is_daylight(timestamps: pd.Series) -> pd.Series:
    """Return True for timestamps inside the assumed daylight window."""
    clock = timestamps.dt.strftime("%H:%M")
    return (clock >= DAYLIGHT_START) & (clock <= DAYLIGHT_END)


def correct_dc_scaling(df: pd.DataFrame) -> pd.DataFrame:
    """Divide DC power by the plant's scaling factor and keep the raw value.

    Plant 1 reports DC power ten times too high (AC/DC median 0.098 on all
    inverters instead of about 0.98).
    """
    df["dc_power_raw"] = df["dc_power"]
    df["flag_dc_rescaled"] = df["plant_id"].isin(DC_SCALE_FACTOR.keys())
    df["dc_power"] = df["dc_power_raw"] / df["plant_id"].map(DC_SCALE_FACTOR).fillna(1.0)
    return df


def add_energy(df: pd.DataFrame) -> pd.DataFrame:
    """Add energy per interval from AC power, replacing the unreliable counters."""
    df["energy_kwh"] = df["ac_power"] * INTERVAL_H
    return df


def add_quality_flags(df: pd.DataFrame) -> pd.DataFrame:
    """Flag suspicious readings and mark the readings that pass all checks."""
    df["flag_no_weather"] = df["irradiation"].isna()
    df["flag_power_without_sun"] = (df["irradiation"] == 0) & (df["ac_power"] > 0)
    df["flag_zero_output_in_sun"] = (df["irradiation"] > SUN_THRESHOLD_ZERO_OUTPUT) & (
        df["ac_power"] == 0
    )
    previous_total = df.groupby("source_key")["total_yield"].shift()
    df["flag_counter_fault"] = (df["total_yield"] == 0) | (df["total_yield"] < previous_total)
    df["is_clean"] = ~df[
        ["flag_no_weather", "flag_power_without_sun", "flag_zero_output_in_sun"]
    ].any(axis=1)
    return df


def build_clean_generation(generation: pd.DataFrame, weather: pd.DataFrame) -> pd.DataFrame:
    """Join weather to every reading and apply corrections, energy and flags."""
    df = generation.merge(weather, on=["plant_id", "date_time"], how="left")
    df = correct_dc_scaling(df)
    df = add_energy(df)
    return add_quality_flags(df)


def find_missing_intervals(df: pd.DataFrame) -> pd.DataFrame:
    """List every expected inverter reading that is absent from the data.

    Each missing row is marked as plant-wide (no inverter of the plant
    reported at that time) and as daylight or night.
    """
    grid = pd.date_range(
        df["date_time"].min().normalize(),
        df["date_time"].max().normalize() + pd.Timedelta("23:45:00"),
        freq="15min",
    )
    inverters = df[["plant_id", "source_key"]].drop_duplicates()
    expected = inverters.merge(pd.DataFrame({"date_time": grid}), how="cross")
    expected = expected.merge(
        df[["source_key", "date_time"]].assign(present=True),
        on=["source_key", "date_time"],
        how="left",
    )
    missing = expected[expected["present"].isna()].drop(columns="present")

    plant_times = df[["plant_id", "date_time"]].drop_duplicates().assign(plant_reported=True)
    missing = missing.merge(plant_times, on=["plant_id", "date_time"], how="left")
    missing["plant_wide"] = missing["plant_reported"].isna()
    missing["daylight"] = is_daylight(missing["date_time"])
    return missing.sort_values(["source_key", "date_time"])


def group_gap_events(missing: pd.DataFrame) -> pd.DataFrame:
    """Merge consecutive missing intervals of one inverter into gap events."""
    new_event = missing.groupby("source_key")["date_time"].diff() != pd.Timedelta("15min")
    missing = missing.assign(event=new_event.cumsum())
    gaps = (
        missing.groupby(["plant_id", "source_key", "event"])
        .agg(
            gap_start=("date_time", "min"),
            gap_end=("date_time", "max"),
            n_intervals=("date_time", "size"),
            daylight_intervals=("daylight", "sum"),
            plant_wide_share=("plant_wide", "mean"),
        )
        .reset_index()
        .drop(columns="event")
    )
    gaps["hours"] = gaps["n_intervals"] * INTERVAL_H
    gaps["scope"] = pd.cut(
        gaps["plant_wide_share"],
        [-0.01, 0.0, 0.999, 1.0],
        labels=["inverter", "mixed", "plant_wide"],
    ).astype(str)
    return gaps


def attach_counter_change(gaps: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
    """Add the total_yield reading just before and just after each gap."""
    counters = df[["source_key", "date_time", "total_yield"]].sort_values("date_time")
    gaps = gaps.sort_values("gap_start").reset_index(drop=True)
    before = pd.merge_asof(
        gaps,
        counters,
        left_on="gap_start",
        right_on="date_time",
        by="source_key",
        direction="backward",
        allow_exact_matches=False,
    )
    gaps["total_before"] = before["total_yield"].to_numpy()
    after = pd.merge_asof(
        gaps.sort_values("gap_end"),
        counters,
        left_on="gap_end",
        right_on="date_time",
        by="source_key",
        direction="forward",
        allow_exact_matches=False,
    )
    gaps = after.drop(columns="date_time").rename(columns={"total_yield": "total_after"})
    gaps["counter_increase_kwh"] = gaps["total_after"] - gaps["total_before"]
    return gaps


def classify_gaps(gaps: pd.DataFrame) -> pd.DataFrame:
    """Label each gap by its likely energy impact.

    * night_only_no_energy_impact: no daylight interval inside the gap.
    * data_loss_energy_recorded: the valid counter rose, so energy was produced.
    * possible_outage: daylight gap and the valid counter did not move.
    * unknown: the counter is missing or faulty around the gap.
    """
    counter_valid = (gaps["total_before"] > 0) & (gaps["total_after"] >= gaps["total_before"])
    has_daylight = gaps["daylight_intervals"] > 0
    gaps["classification"] = "unknown"
    gaps.loc[~has_daylight, "classification"] = "night_only_no_energy_impact"
    gaps.loc[
        has_daylight & counter_valid & (gaps["counter_increase_kwh"] > 0), "classification"
    ] = "data_loss_energy_recorded"
    gaps.loc[
        has_daylight & counter_valid & (gaps["counter_increase_kwh"] == 0), "classification"
    ] = "possible_outage"
    return gaps.drop(columns="plant_wide_share").sort_values(
        ["plant_id", "source_key", "gap_start"]
    )


def build_gap_table(df: pd.DataFrame) -> pd.DataFrame:
    """Find, group and classify all gaps in the generation data."""
    gaps = group_gap_events(find_missing_intervals(df))
    gaps = attach_counter_change(gaps, df)
    return classify_gaps(gaps)


def write_tables(clean: pd.DataFrame, gaps: pd.DataFrame) -> None:
    """Replace generation_clean and data_gaps in the database."""
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS generation_clean, data_gaps;"))
    clean.to_sql("generation_clean", engine, index=False, chunksize=10_000)
    gaps.to_sql("data_gaps", engine, index=False)


def print_summary(clean: pd.DataFrame, gaps: pd.DataFrame) -> None:
    """Print flag counts, the clean share and the gap classification."""
    flag_cols = [c for c in clean.columns if c.startswith("flag_")]
    print(f"generation_clean: {len(clean):,} rows")
    print(clean.groupby("plant_id")[flag_cols].sum().T.to_string())
    print(f"\nShare of clean rows: {clean['is_clean'].mean():.1%}")
    print(f"\ndata_gaps: {len(gaps):,} gap events, {gaps['n_intervals'].sum():,} missing intervals")
    summary = gaps.groupby(["plant_id", "classification"]).agg(
        events=("n_intervals", "size"),
        intervals=("n_intervals", "sum"),
        daylight_intervals=("daylight_intervals", "sum"),
    )
    print(summary.to_string())


def main() -> None:
    """Run the full validation pipeline."""
    generation, weather = load_raw()
    clean = build_clean_generation(generation, weather)
    gaps = build_gap_table(clean)
    write_tables(clean, gaps)
    print_summary(clean, gaps)


if __name__ == "__main__":
    main()
