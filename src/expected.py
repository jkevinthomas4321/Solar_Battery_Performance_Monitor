"""Model expected inverter output and classify the shortfall against it.

Physics model per 15-minute interval:
    expected_kw = capacity x G x (1 + gamma x (T_module - 25)) x efficiency

A linear regression trained on healthy inverters cross-checks the model. The
shortfall (expected - actual) is split into downtime, clipping and
underperformance, and inverters with a sustained low performance index are
flagged.

Reads ``generation_clean``, ``data_gaps``, ``weather``, ``kpi_plant`` and
``kpi_inverter``. Writes ``expected_power``, ``expected_daily``,
``model_validation`` and figures in reports/figures.

Usage:
    python src/expected.py
"""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sqlalchemy import text

from config import (
    CLIPPING_MARGIN,
    FIGURES_DIR,
    GAMMA,
    INTERVAL_H,
    MIN_DAY_COMPLETENESS,
    PROCESSED_DIR,
    SUN_THRESHOLD_AVAILABILITY,
    SUSTAINED_DAYS,
    SUSTAINED_PI_THRESHOLD,
    UNDERPERFORMANCE_TOLERANCE,
)
from db import get_engine

SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID = "#e4e3df"
INCOMPLETE_DAY = "#d6d5d0"
SERIES_ACTUAL = "#2a78d6"
SERIES_EXPECTED = "#eb6834"
SEQUENTIAL_BLUE = ["#fcfcfb", "#cde2fb", "#86b6ef", "#3987e5", "#256abf", "#184f95", "#0d366b"]


def load_inputs() -> dict[str, pd.DataFrame]:
    """Read the clean readings, gaps, weather and the Phase 4 KPI tables."""
    engine = get_engine()
    tables = {
        "generation": "SELECT plant_id, source_key, date_time, ac_power, dc_power, irradiation, "
        "module_temperature, is_clean FROM generation_clean",
        "gaps": "SELECT * FROM data_gaps WHERE classification = 'possible_outage'",
        "weather": "SELECT plant_id, date_time, irradiation, module_temperature FROM weather",
        "plant": "SELECT plant_id, capacity_kwp_per_inverter, efficiency FROM kpi_plant",
        "inverter": "SELECT plant_id, source_key, pr_rank FROM kpi_inverter",
    }
    return {name: pd.read_sql(query, engine) for name, query in tables.items()}


def physics_expected(df: pd.DataFrame, plant: pd.DataFrame) -> pd.Series:
    """Expected AC power (kW) from irradiance, module temperature and plant constants."""
    params = df[["plant_id"]].merge(plant, on="plant_id", how="left")
    temperature_factor = 1 + GAMMA * (df["module_temperature"].to_numpy() - 25)
    return pd.Series(
        params["capacity_kwp_per_inverter"].to_numpy()
        * df["irradiation"].to_numpy()
        * temperature_factor
        * params["efficiency"].to_numpy(),
        index=df.index,
    )


def outage_gap_rows(gaps: pd.DataFrame, weather: pd.DataFrame) -> pd.DataFrame:
    """Rows for missing intervals classified as possible_outage, counted as zero output."""
    rows = [
        (gap.plant_id, gap.source_key, ts)
        for gap in gaps.itertuples()
        for ts in pd.date_range(gap.gap_start, gap.gap_end, freq="15min")
    ]
    missing = pd.DataFrame(rows, columns=["plant_id", "source_key", "date_time"])
    missing = missing.merge(weather, on=["plant_id", "date_time"], how="inner")
    return missing.assign(ac_power=0.0, dc_power=0.0, is_clean=False, from_gap=True)


def build_interval_table(inputs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Sunny intervals of every inverter with actual and expected power."""
    readings = inputs["generation"].assign(from_gap=False)
    readings = pd.concat([readings, outage_gap_rows(inputs["gaps"], inputs["weather"])])
    df = readings[readings["irradiation"] > SUN_THRESHOLD_AVAILABILITY].copy()
    df = df.dropna(subset=["module_temperature"]).reset_index(drop=True)
    df["expected_kw"] = physics_expected(df, inputs["plant"])
    df["day"] = df["date_time"].dt.normalize()
    return df


def healthy_mask(df: pd.DataFrame, inverter: pd.DataFrame) -> pd.Series:
    """Clean, producing readings from the better half of each plant's inverters."""
    top_half = inverter.loc[inverter["pr_rank"] <= 11, "source_key"]
    return df["is_clean"] & (df["ac_power"] > 0) & df["source_key"].isin(top_half)


def fit_metrics(actual: pd.Series, predicted: pd.Series) -> dict[str, float]:
    """MAE, normalised MAE, bias and R2 of a prediction."""
    residual = actual - predicted
    return {
        "mae_kw": residual.abs().mean(),
        "nmae": residual.abs().mean() / actual.mean(),
        "bias_kw": residual.mean(),
        "r2": 1 - (residual**2).sum() / ((actual - actual.mean()) ** 2).sum(),
    }


def regression_cross_check(df: pd.DataFrame, healthy: pd.Series) -> pd.DataFrame:
    """Compare the physics model with a regression trained on healthy days.

    Days are split 70/30 per plant (fixed seed) so that test days are unseen.
    Features follow the physics: G and G x (T - 25). The ratio of the two
    coefficients gives a data-based estimate of the temperature coefficient.
    """
    results = []
    rng = np.random.default_rng(42)
    for plant_id, data in df[healthy].groupby("plant_id"):
        days = data["day"].unique()
        test_days = rng.choice(days, size=int(len(days) * 0.3), replace=False)
        test = data["day"].isin(test_days)
        features = np.column_stack(
            [data["irradiation"], data["irradiation"] * (data["module_temperature"] - 25)]
        )
        model = LinearRegression(fit_intercept=False).fit(features[~test], data["ac_power"][~test])
        predicted = pd.Series(model.predict(features[test]), index=data.index[test])
        actual = data.loc[test, "ac_power"]
        for name, prediction in [
            ("physics", data.loc[test, "expected_kw"]),
            ("regression", predicted),
        ]:
            results.append(
                {
                    "plant_id": plant_id,
                    "model": name,
                    "n_test": int(test.sum()),
                    **fit_metrics(actual, prediction),
                    "gamma_estimate": model.coef_[1] / model.coef_[0]
                    if name == "regression"
                    else GAMMA,
                }
            )
    return pd.DataFrame(results)


def classify_intervals(df: pd.DataFrame) -> pd.DataFrame:
    """Assign each sunny interval to downtime, clipping or running, and its lost energy.

    * downtime: zero output (reported or possible-outage gap).
    * clipping: output within CLIPPING_MARGIN of the plant's maximum AC power
      while the model expects more.
    * running: producing; its net shortfall beyond the tolerance band is underperformance.
    """
    clip_level = df.groupby("plant_id")["ac_power"].transform("max") * (1 - CLIPPING_MARGIN)
    df["category"] = "running"
    df.loc[(df["ac_power"] >= clip_level) & (df["expected_kw"] > df["ac_power"]), "category"] = (
        "clipping"
    )
    df.loc[df["ac_power"] == 0, "category"] = "downtime"
    df["shortfall_kwh"] = (df["expected_kw"] - df["ac_power"]) * INTERVAL_H
    df["performance_index"] = df["ac_power"] / df["expected_kw"]
    return df


def daily_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Daily expected and actual energy, losses by category and performance index."""
    by = ["plant_id", "source_key", "day"]
    totals = df.groupby(by).agg(
        expected_kwh=("expected_kw", lambda s: s.sum() * INTERVAL_H),
        actual_kwh=("ac_power", lambda s: s.sum() * INTERVAL_H),
        sunny_intervals=("expected_kw", "size"),
    )
    losses = (
        df.pivot_table(index=by, columns="category", values="shortfall_kwh", aggfunc="sum")
        .reindex(columns=["downtime", "clipping", "running"])
        .fillna(0.0)
    )
    losses.columns = ["downtime_loss_kwh", "clipping_loss_kwh", "net_running_shortfall_kwh"]
    running = df[df["category"] == "running"].groupby(by)
    expected_running = (running["expected_kw"].sum() * INTERVAL_H).rename("expected_running_kwh")
    pi_running = (running["ac_power"].sum() / running["expected_kw"].sum()).rename("pi_running")

    daily = totals.join(losses).join(expected_running).join(pi_running).reset_index()
    daily["expected_running_kwh"] = daily["expected_running_kwh"].fillna(0.0)
    daily["pi_total"] = daily["actual_kwh"] / daily["expected_kwh"]
    readings_per_day = df[~df["from_gap"]].groupby(by).size().rename("n_readings")
    daily = daily.merge(readings_per_day.reset_index(), on=by, how="left")
    sunny_per_day = daily.groupby(["plant_id", "day"])["sunny_intervals"].transform("max")
    daily["complete"] = daily["n_readings"] >= MIN_DAY_COMPLETENESS * sunny_per_day
    return flag_sustained_underperformance(daily)


def flag_sustained_underperformance(daily: pd.DataFrame) -> pd.DataFrame:
    """Flag runs of at least SUSTAINED_DAYS consecutive calendar days with low pi_running.

    A low day is a complete day with pi_running below SUSTAINED_PI_THRESHOLD.
    A missing or incomplete day breaks the run.
    """
    daily = daily.sort_values(["source_key", "day"]).reset_index(drop=True)
    low = daily["complete"] & (daily["pi_running"] < SUSTAINED_PI_THRESHOLD)
    by_inverter = daily.groupby("source_key")
    next_calendar_day = by_inverter["day"].diff() == pd.Timedelta("1D")
    continues_run = (
        low & low.groupby(daily["source_key"]).shift(fill_value=False) & next_calendar_day
    )
    run_id = (~continues_run).cumsum()
    run_length = low.groupby(run_id).transform("sum")
    daily["low_pi_day"] = low
    daily["sustained_underperformance"] = low & (run_length >= SUSTAINED_DAYS)
    return daily


def inverter_summary(daily: pd.DataFrame) -> pd.DataFrame:
    """Period totals per inverter: energy, losses by category and sustained flags.

    Underperformance counts only the running shortfall beyond the tolerance band
    (UNDERPERFORMANCE_TOLERANCE of expected running energy). Smaller deviations
    reflect normal differences between arrays and model uncertainty, not faults.
    """
    summary = daily.groupby(["plant_id", "source_key"]).agg(
        expected_mwh=("expected_kwh", lambda s: s.sum() / 1000),
        actual_mwh=("actual_kwh", lambda s: s.sum() / 1000),
        downtime_loss_mwh=("downtime_loss_kwh", lambda s: s.sum() / 1000),
        clipping_loss_mwh=("clipping_loss_kwh", lambda s: s.sum() / 1000),
        net_running_shortfall_mwh=("net_running_shortfall_kwh", lambda s: s.sum() / 1000),
        expected_running_mwh=("expected_running_kwh", lambda s: s.sum() / 1000),
        sustained_days=("sustained_underperformance", "sum"),
    )
    tolerance_mwh = UNDERPERFORMANCE_TOLERANCE * summary["expected_running_mwh"]
    summary["underperformance_mwh"] = (summary["net_running_shortfall_mwh"] - tolerance_mwh).clip(
        lower=0
    )
    complete = daily[daily["complete"]].groupby("source_key")
    summary = summary.join(complete["pi_running"].median().rename("median_pi_running"))
    summary["total_loss_mwh"] = summary[
        ["downtime_loss_mwh", "clipping_loss_mwh", "underperformance_mwh"]
    ].sum(axis=1)
    return summary.reset_index().sort_values("total_loss_mwh", ascending=False)


def style_axes(ax: plt.Axes, title: str, xlabel: str, ylabel: str) -> None:
    """Apply the shared chart style: recessive grid and axes, text in text colours."""
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", color=TEXT_PRIMARY, fontsize=12, fontweight="bold")
    ax.set_xlabel(xlabel, color=TEXT_SECONDARY)
    ax.set_ylabel(ylabel, color=TEXT_SECONDARY)
    ax.tick_params(colors=TEXT_SECONDARY, labelsize=9)
    ax.grid(color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ["top", "right"]:
        ax.spines[side].set_visible(False)
    for side in ["left", "bottom"]:
        ax.spines[side].set_color(GRID)


def plot_model_fit(df: pd.DataFrame, healthy: pd.Series, source_key: str) -> None:
    """Scatter of actual vs expected power for one healthy inverter."""
    data = df[healthy & (df["source_key"] == source_key)]
    fig, ax = plt.subplots(figsize=(6, 6), facecolor=SURFACE)
    limit = max(data["expected_kw"].max(), data["ac_power"].max()) * 1.05
    ax.plot([0, limit], [0, limit], color=TEXT_SECONDARY, linewidth=1, linestyle="--")
    ax.scatter(
        data["expected_kw"], data["ac_power"], s=9, color=SERIES_ACTUAL, alpha=0.35, linewidths=0
    )
    ax.text(
        limit * 0.97, limit * 0.9, "actual = expected", color=TEXT_SECONDARY, ha="right", fontsize=9
    )
    style_axes(
        ax,
        f"Model fit, healthy inverter {source_key}",
        "Expected AC power (kW)",
        "Actual AC power (kW)",
    )
    ax.set_xlim(0, limit)
    ax.set_ylim(0, limit)
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "expected_model_fit.png", dpi=150)
    plt.close(fig)


def plot_day_profile(df: pd.DataFrame, source_key: str, day: pd.Timestamp) -> None:
    """Expected vs actual power over one day for one inverter."""
    data = df[(df["source_key"] == source_key) & (df["day"] == day)].sort_values("date_time")
    fig, ax = plt.subplots(figsize=(9, 4.5), facecolor=SURFACE)
    ax.plot(
        data["date_time"], data["expected_kw"], color=SERIES_EXPECTED, linewidth=2, label="Expected"
    )
    ax.plot(data["date_time"], data["ac_power"], color=SERIES_ACTUAL, linewidth=2, label="Actual")
    ax.fill_between(
        data["date_time"],
        data["ac_power"],
        data["expected_kw"],
        where=data["expected_kw"] > data["ac_power"],
        color=SERIES_EXPECTED,
        alpha=0.12,
        linewidth=0,
    )
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%H:%M"))
    style_axes(ax, f"Expected vs actual, {source_key}, {day:%d %b %Y}", "Time", "AC power (kW)")
    ax.legend(frameon=False, labelcolor=TEXT_PRIMARY, loc="upper left")
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "expected_day_profile.png", dpi=150)
    plt.close(fig)


def plot_pi_heatmap(daily: pd.DataFrame, plant_id: int) -> None:
    """Daily shortfall (1 - performance index) per inverter for one plant."""
    data = daily[(daily["plant_id"] == plant_id) & daily["complete"]]
    grid = data.pivot_table(index="source_key", columns="day", values="pi_total")
    grid = grid.loc[grid.mean(axis=1).sort_values().index]
    shortfall = (1 - grid).clip(lower=0, upper=1)
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list("shortfall", SEQUENTIAL_BLUE)
    cmap.set_bad(INCOMPLETE_DAY)
    fig, ax = plt.subplots(figsize=(11, 6.5), facecolor=SURFACE)
    image = ax.imshow(shortfall.to_numpy(), aspect="auto", cmap=cmap, vmin=0, vmax=1)
    ax.set_yticks(range(len(shortfall.index)), shortfall.index, fontsize=8)
    ax.set_xticks(
        range(0, len(shortfall.columns), 3),
        [f"{d:%d %b}" for d in shortfall.columns[::3]],
        fontsize=8,
    )
    style_axes(ax, f"Daily energy shortfall vs expected, plant {plant_id}", "Day", "Inverter")
    ax.grid(False)
    bar = fig.colorbar(image, ax=ax, fraction=0.03, pad=0.02)
    bar.set_label("Shortfall (1 - actual / expected)", color=TEXT_SECONDARY)
    bar.ax.tick_params(colors=TEXT_SECONDARY, labelsize=8)
    bar.outline.set_visible(False)
    fig.text(
        0.01, 0.01, "Grey: incomplete day (data gap), excluded", color=TEXT_SECONDARY, fontsize=8
    )
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / f"expected_shortfall_heatmap_{plant_id}.png", dpi=150)
    plt.close(fig)


def write_outputs(
    df: pd.DataFrame, daily: pd.DataFrame, validation: pd.DataFrame, inverters: pd.DataFrame
) -> None:
    """Replace the Phase 5 tables in the database and export CSV copies."""
    interval_cols = [
        "plant_id",
        "source_key",
        "date_time",
        "irradiation",
        "module_temperature",
        "ac_power",
        "expected_kw",
        "performance_index",
        "category",
        "shortfall_kwh",
        "from_gap",
    ]
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                "DROP TABLE IF EXISTS expected_power, expected_daily, expected_inverter, "
                "model_validation;"
            )
        )
    df[interval_cols].to_sql("expected_power", engine, index=False, chunksize=10_000)
    daily.to_sql("expected_daily", engine, index=False)
    inverters.to_sql("expected_inverter", engine, index=False)
    validation.to_sql("model_validation", engine, index=False)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    daily.to_csv(PROCESSED_DIR / "expected_daily.csv", index=False)
    inverters.to_csv(PROCESSED_DIR / "expected_inverter.csv", index=False)


def print_summary(validation: pd.DataFrame, inverters: pd.DataFrame) -> None:
    """Print model accuracy, losses per plant and the inverters with the largest losses."""
    pd.set_option("display.width", 160)
    print("Model validation on unseen healthy days")
    print(validation.round(4).to_string(index=False))
    loss_cols = [
        "expected_mwh",
        "actual_mwh",
        "downtime_loss_mwh",
        "clipping_loss_mwh",
        "underperformance_mwh",
        "total_loss_mwh",
    ]
    print("\nEnergy and losses per plant (MWh, sunny intervals)")
    print(inverters.groupby("plant_id")[loss_cols].sum().round(1).to_string())
    print("\nInverters with sustained underperformance (days)")
    flagged = inverters[inverters["sustained_days"] > 0]
    print(
        flagged[["plant_id", "source_key", "sustained_days", "median_pi_running"]]
        .round(3)
        .to_string(index=False)
        if len(flagged)
        else "none"
    )
    print("\nTop 10 inverters by total loss")
    print(inverters.head(10).round(2).to_string(index=False))


def main() -> None:
    """Run the expected-performance pipeline."""
    inputs = load_inputs()
    df = build_interval_table(inputs)
    healthy = healthy_mask(df, inputs["inverter"])
    validation = regression_cross_check(df, healthy)
    df = classify_intervals(df)
    daily = daily_summary(df)
    inverters = inverter_summary(daily)

    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    best = inputs["inverter"].sort_values("pr_rank").iloc[0]["source_key"]
    plot_model_fit(df, healthy, best)
    worst_day = daily[daily["complete"]].sort_values("downtime_loss_kwh").iloc[-1]
    plot_day_profile(df, worst_day["source_key"], worst_day["day"])
    for plant_id in sorted(df["plant_id"].unique()):
        plot_pi_heatmap(daily, plant_id)

    write_outputs(df, daily, validation, inverters)
    print_summary(validation, inverters)


if __name__ == "__main__":
    main()
