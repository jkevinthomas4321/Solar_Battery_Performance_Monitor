"""Calculate performance KPIs per inverter-day, per inverter and per plant.

Reads ``generation_clean``, ``data_gaps`` and ``weather`` and writes the tables
``kpi_daily``, ``kpi_inverter`` and ``kpi_plant`` plus CSV copies in
data/processed for the dashboard.

Assumptions:
    A1  Capacity per inverter is estimated as the median of
        DC / (G x (1 + gamma x (T_module - 25))) over clean readings with
        G >= 0.5 kW/m2. The plant median is applied to every inverter.
    A2  gamma = -0.4 %/degC.
    A3  The irradiation sensor measures plane-of-array irradiance.
    A4  An interval is sunny when irradiation > 0.1 kW/m2.
    A5  PR uses only days with >= 90 % of inverter and weather readings.

Usage:
    python src/kpis.py
"""

import pandas as pd
from sqlalchemy import text

from config import (
    G_MIN_CAPACITY,
    GAMMA,
    INTERVAL_H,
    MIN_DAY_COMPLETENESS,
    PROCESSED_DIR,
    READINGS_PER_DAY,
    SUN_THRESHOLD_AVAILABILITY,
)
from db import get_engine


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Read the clean generation data, the gap table and the weather data."""
    engine = get_engine()
    generation = pd.read_sql("SELECT * FROM generation_clean", engine)
    gaps = pd.read_sql("SELECT * FROM data_gaps", engine)
    weather = pd.read_sql(
        "SELECT plant_id, date_time, irradiation, module_temperature FROM weather", engine
    )
    generation["day"] = generation["date_time"].dt.normalize()
    weather["day"] = weather["date_time"].dt.normalize()
    return generation, gaps, weather


def estimate_capacity(generation: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Estimate the effective DC capacity at standard test conditions (A1, A2).

    Returns:
        Capacity per inverter and capacity per plant (median over inverters), in kWp.
    """
    ref = generation[
        generation["is_clean"]
        & (generation["irradiation"] >= G_MIN_CAPACITY)
        & (generation["dc_power"] > 0)
    ]
    temperature_factor = 1 + GAMMA * (ref["module_temperature"] - 25)
    p_stc = ref["dc_power"] / (ref["irradiation"] * temperature_factor)
    per_inverter = (
        p_stc.groupby([ref["plant_id"], ref["source_key"]]).median().rename("capacity_own_kwp")
    )
    per_plant = per_inverter.groupby("plant_id").median().rename("capacity_kwp")
    return per_inverter, per_plant


def daily_insolation(weather: pd.DataFrame) -> pd.DataFrame:
    """Sum irradiation into daily insolation (kWh/m2) per plant."""
    return (
        weather.groupby(["plant_id", "day"])
        .agg(
            insolation_kwh_m2=("irradiation", lambda s: s.sum() * INTERVAL_H),
            n_weather=("irradiation", "size"),
        )
        .reset_index()
    )


def daily_energy_and_pr(
    generation: pd.DataFrame, weather: pd.DataFrame, capacity_plant: pd.Series
) -> pd.DataFrame:
    """Daily energy, specific yield and performance ratio per inverter (A5)."""
    daily = (
        generation.groupby(["plant_id", "source_key", "day"])
        .agg(energy_kwh=("energy_kwh", "sum"), n_readings=("energy_kwh", "size"))
        .reset_index()
    )
    daily = daily.merge(daily_insolation(weather), on=["plant_id", "day"], how="left")
    daily = daily.merge(capacity_plant, on="plant_id")
    daily["completeness"] = daily["n_readings"] / READINGS_PER_DAY
    daily["pr_valid"] = (daily["completeness"] >= MIN_DAY_COMPLETENESS) & (
        daily["n_weather"] / READINGS_PER_DAY >= MIN_DAY_COMPLETENESS
    )
    daily["specific_yield"] = daily["energy_kwh"] / daily["capacity_kwp"]
    daily["pr"] = (daily["specific_yield"] / daily["insolation_kwh_m2"]).where(daily["pr_valid"])
    return daily


def expand_gaps(gaps: pd.DataFrame) -> pd.DataFrame:
    """Turn each gap event into one row per missing 15-minute interval."""
    rows = [
        (gap.source_key, ts, gap.classification)
        for gap in gaps.itertuples()
        for ts in pd.date_range(gap.gap_start, gap.gap_end, freq="15min")
    ]
    return pd.DataFrame(rows, columns=["source_key", "date_time", "gap_class"])


def sunny_interval_status(
    generation: pd.DataFrame, gaps: pd.DataFrame, weather: pd.DataFrame
) -> pd.DataFrame:
    """Label every sunny interval of every inverter as up, down or excluded (A4).

    * up: the inverter produced power.
    * down: it reported zero, or its gap is classified as possible_outage.
    * excluded: data missing but energy was likely produced (communication loss).
    """
    sunny = weather.loc[
        weather["irradiation"] > SUN_THRESHOLD_AVAILABILITY, ["plant_id", "date_time", "day"]
    ]
    inverters = generation[["plant_id", "source_key"]].drop_duplicates()
    status = sunny.merge(inverters, on="plant_id")
    status = status.merge(
        generation[["source_key", "date_time", "ac_power"]],
        on=["source_key", "date_time"],
        how="left",
    )
    status = status.merge(expand_gaps(gaps), on=["source_key", "date_time"], how="left")
    status["state"] = "excluded"
    status.loc[status["ac_power"] > 0, "state"] = "up"
    status.loc[status["ac_power"] == 0, "state"] = "down"
    status.loc[status["ac_power"].isna() & (status["gap_class"] == "possible_outage"), "state"] = (
        "down"
    )
    return status


def add_availability(daily: pd.DataFrame, status: pd.DataFrame) -> pd.DataFrame:
    """Add sunny intervals up/down and daily availability to the daily table."""
    counts = (
        status.assign(up=status["state"].eq("up"), down=status["state"].eq("down"))
        .groupby(["plant_id", "source_key", "day"])[["up", "down"]]
        .sum()
        .reset_index()
    )
    daily = daily.merge(counts, on=["plant_id", "source_key", "day"], how="left")
    daily[["up", "down"]] = daily[["up", "down"]].fillna(0)
    daily["availability"] = daily["up"] / (daily["up"] + daily["down"])
    return daily


def inverter_efficiency(generation: pd.DataFrame) -> pd.Series:
    """Energy-weighted AC/DC ratio per inverter while producing."""
    producing = generation[generation["dc_power"] > 0]
    by_inverter = producing.groupby("source_key")
    return (by_inverter["ac_power"].sum() / by_inverter["dc_power"].sum()).rename("efficiency")


def inverter_kpis(
    daily: pd.DataFrame,
    generation: pd.DataFrame,
    capacity_inverter: pd.Series,
    capacity_plant: pd.Series,
) -> pd.DataFrame:
    """Aggregate the period KPIs per inverter and rank inverters within each plant."""
    valid = daily[daily["pr_valid"]]
    inv = (
        valid.groupby(["plant_id", "source_key"])
        .agg(
            valid_days=("day", "size"),
            energy_valid_kwh=("energy_kwh", "sum"),
            insolation_valid=("insolation_kwh_m2", "sum"),
        )
        .reset_index()
    )
    inv = inv.merge(capacity_plant, on="plant_id")
    inv = inv.merge(capacity_inverter.reset_index(), on=["plant_id", "source_key"])
    inv["pr"] = inv["energy_valid_kwh"] / (inv["capacity_kwp"] * inv["insolation_valid"])
    inv["specific_yield_per_day"] = (
        inv["energy_valid_kwh"] / inv["capacity_kwp"] / inv["valid_days"]
    )

    totals = daily.groupby("source_key").agg(
        energy_total_kwh=("energy_kwh", "sum"), up=("up", "sum"), down=("down", "sum")
    )
    totals["availability"] = totals["up"] / (totals["up"] + totals["down"])
    totals["downtime_hours"] = totals["down"] * INTERVAL_H
    inv = inv.merge(
        totals[["energy_total_kwh", "availability", "downtime_hours"]].reset_index(),
        on="source_key",
    )
    inv = inv.merge(inverter_efficiency(generation).reset_index(), on="source_key")

    by_plant = inv.groupby("plant_id")
    inv["pr_rank"] = by_plant["pr"].rank(ascending=False, method="min").astype(int)
    inv["availability_rank"] = (
        by_plant["availability"].rank(ascending=False, method="min").astype(int)
    )
    inv["is_bottom_5"] = by_plant["pr"].rank(ascending=True, method="first") <= 5
    return inv.sort_values(["plant_id", "pr_rank"])


def plant_kpis(inv: pd.DataFrame) -> pd.DataFrame:
    """Aggregate the inverter KPIs to plant level."""
    plant = (
        inv.groupby("plant_id")
        .agg(
            capacity_kwp_per_inverter=("capacity_kwp", "first"),
            energy_total_mwh=("energy_total_kwh", lambda s: s.sum() / 1000),
            energy_valid_kwh=("energy_valid_kwh", "sum"),
            insolation_valid=("insolation_valid", "mean"),
            availability=("availability", "mean"),
            downtime_hours=("downtime_hours", "sum"),
            efficiency=("efficiency", "mean"),
            n_inverters=("source_key", "size"),
        )
        .reset_index()
    )
    installed_kwp = plant["capacity_kwp_per_inverter"] * plant["n_inverters"]
    plant["pr"] = plant["energy_valid_kwh"] / (installed_kwp * plant["insolation_valid"])
    plant["capacity_mwp"] = installed_kwp / 1000
    return plant.drop(columns=["energy_valid_kwh", "insolation_valid"])


def write_outputs(daily: pd.DataFrame, inv: pd.DataFrame, plant: pd.DataFrame) -> None:
    """Replace the KPI tables in the database and export them as CSV."""
    daily_out = daily.drop(columns="capacity_kwp").rename(
        columns={"up": "sunny_intervals_up", "down": "sunny_intervals_down"}
    )
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS kpi_daily, kpi_inverter, kpi_plant;"))
    daily_out.to_sql("kpi_daily", engine, index=False)
    inv.to_sql("kpi_inverter", engine, index=False)
    plant.to_sql("kpi_plant", engine, index=False)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    daily_out.to_csv(PROCESSED_DIR / "kpi_daily.csv", index=False)
    inv.to_csv(PROCESSED_DIR / "kpi_inverter.csv", index=False)
    plant.to_csv(PROCESSED_DIR / "kpi_plant.csv", index=False)


def print_summary(inv: pd.DataFrame, plant: pd.DataFrame) -> None:
    """Print plant KPIs, the bottom five inverters and the PR range."""
    pd.set_option("display.width", 160)
    print("Plant KPIs")
    print(plant.round(3).to_string(index=False))
    print("\nBottom five inverters per plant (by PR)")
    cols = [
        "plant_id",
        "source_key",
        "pr",
        "availability",
        "downtime_hours",
        "efficiency",
        "valid_days",
    ]
    print(inv.loc[inv["is_bottom_5"], cols].round(3).to_string(index=False))
    print("\nPR range per plant")
    print(inv.groupby("plant_id")["pr"].describe()[["min", "50%", "max"]].round(3).to_string())


def main() -> None:
    """Run the KPI pipeline."""
    generation, gaps, weather = load_inputs()
    capacity_inverter, capacity_plant = estimate_capacity(generation)
    daily = daily_energy_and_pr(generation, weather, capacity_plant)
    daily = add_availability(daily, sunny_interval_status(generation, gaps, weather))
    inv = inverter_kpis(daily, generation, capacity_inverter, capacity_plant)
    plant = plant_kpis(inv)
    write_outputs(daily, inv, plant)
    print_summary(inv, plant)


if __name__ == "__main__":
    main()
