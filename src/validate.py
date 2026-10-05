# validate.py
#
# Takes the raw solar data, fixes what can be fixed, labels what can't, and saves
# two clean tables that all later phases work from:
#   generation_clean - every reading, with corrected DC power, energy and quality flags
#   data_gaps        - every gap in the data, and whether it actually cost energy
#
# The raw tables (generation, weather) are only read, never changed. If I ever
# need to start over, I just rerun this script.
#
# Problems this script deals with (all found with the queries in sql/03 to sql/07):
#   1. Plant 1 reports DC power 10x too high                -> corrected
#   2. Plant 2's energy counters can't be trusted           -> energy calculated from AC power instead
#   3. A few readings have no weather data                  -> flagged
#   4. Some readings show power while the sensor says no sun -> flagged
#   5. Inverters producing nothing in good sun              -> flagged (likely real downtime)
#   6. Missing readings                                     -> not filled in, listed in data_gaps
#   7. Inverters that went silent but kept producing        -> gaps checked against the counter

# =====================================================================================
# Run from the repo root:  python src/validate.py

import pandas as pd
from sqlalchemy import text
from db import engine


# Assumptions 


INTERVAL_H = 0.25                  # one reading every 15 minutes = 0.25 hours
DC_SCALE = {4135001: 10.0}         # Plant 1's DC values need dividing by 10 (see sql/06)
SUN_THRESHOLD = 0.2                # above 0.2 kW/m2 an inverter really should be producing
DAYLIGHT = ("06:00", "18:30")      # rough daylight window; gaps outside it cost no energy


def is_daylight(ts: pd.Series) -> pd.Series:
    """True if the timestamp falls inside the daylight window."""
    t = ts.dt.strftime("%H:%M")
    return (t >= DAYLIGHT[0]) & (t <= DAYLIGHT[1])


# 1. Read the raw data 
# Load both tables and sort the readings by inverter and time. The sorting matters:
# further down I compare each reading with the one before it from the same inverter.

gen = pd.read_sql("SELECT * FROM generation", engine)
wea = pd.read_sql(
    "SELECT plant_id, date_time, ambient_temperature, module_temperature, irradiation FROM weather",
    engine)
gen = gen.sort_values(["source_key", "date_time"]).reset_index(drop=True)
print(f"Read {len(gen):,} generation rows and {len(wea):,} weather rows")


# 2. Fix and label every reading 

# Give each inverter reading the weather at that plant at that moment.
# Readings without a weather match are kept; their weather columns are just empty.
# I need the weather for the checks below, and later for the expected-output model.
df = gen.merge(wea, on=["plant_id", "date_time"], how="left")

# Fixes problem 1: Plant 1's DC power is 10x too high.
# AC/DC came out at 0.098 instead of ~0.98, the same on all 22 inverters, so it's a
# unit/scaling error and not a real fault. I keep the original value in dc_power_raw
# and divide by 10 for Plant 1 only (Plant 2 is divided by 1, so it stays the same).
df["dc_power_raw"] = df["dc_power"]
df["flag_dc_rescaled"] = df["plant_id"].isin(DC_SCALE.keys())
df["dc_power"] = df["dc_power_raw"] / df["plant_id"].map(DC_SCALE).fillna(1.0)

# Fixes problem 2: Plant 2's energy counters are unreliable.
# Its total_yield goes backwards, drops to 0 and even reaches 2.25 TWh, and its daily_yield
# doesn't reset properly. So instead of the counters, I calculate energy myself:
# power (kW) x 0.25 h = energy (kWh) per reading. Same method for both plants.
df["energy_kwh"] = df["ac_power"] * INTERVAL_H


# Fixes problem 3: some readings have no weather data (4 in Plant 1).
# I can't compare these with what the plant should have produced, so I mark them.
df["flag_no_weather"] = df["irradiation"].isna()

# Fixes problem 4: power while the irradiation sensor reads zero.
# 14 Plant 2 readings, all between 18:00 and 19:00 and at most 2 kW. Most likely the sensor
# drops to zero at dusk slightly before the inverters do. Harmless, but I don't want these
# readings in the reference data, so they get a flag.
df["flag_power_without_sun"] = (df["irradiation"] == 0) & (df["ac_power"] > 0)

# Fixes problem 5: inverters producing nothing in good sun.
# This isn't bad data, it's where real downtime shows up (63 cases in Plant 1, 3,758 in
# Plant 2). I flag these instead of deleting them, because the loss analysis needs them.
df["flag_zero_output_in_sun"] = (df["irradiation"] > SUN_THRESHOLD) & (df["ac_power"] == 0)

# Also part of problem 2: mark where the lifetime counter is broken.
# A lifetime counter should only go up. I flag it when it's 0 or lower than the previous
# reading of the same inverter. shift() gives me that previous reading (like LAG in SQL).
# I use this flag further down, so a broken counter never decides whether a gap lost energy.
prev_total = df.groupby("source_key")["total_yield"].shift()
df["flag_counter_fault"] = (df["total_yield"] == 0) | (df["total_yield"] < prev_total)

# One overall yes/no label: is this reading safe to use as "healthy" reference data?
# It's clean when it has weather data, no power without sun, and no zero output in sun.
# The counter flag isn't included, because energy no longer comes from the counters.
# Phase 5 will learn what normal output looks like from these clean readings only.
flag_cols = [c for c in df.columns if c.startswith("flag_")]
df["is_clean"] = ~df[["flag_no_weather", "flag_power_without_sun", "flag_zero_output_in_sun"]].any(axis=1)


# --- 3. Find every gap and decide whether it cost energy --------------------------------
# Fixes problems 6 and 7. Missing readings make energy totals too low, and a long gap is
# easy to mistake for an inverter being down. I don't fill the gaps in. Instead I list each
# one and work out whether real energy was lost, so the loss analysis only counts real outages.

# Step 3a: work out which readings are missing.
# Build every reading that should exist (each inverter x every 15 minutes = 143,616),
# match it against the real data, and keep the ones with no match.
# Same idea as generate_series + LEFT JOIN + IS NULL in sql/03.
grid = pd.date_range(
    df["date_time"].min().normalize(),
    df["date_time"].max().normalize() + pd.Timedelta("23:45:00"),
    freq="15min",
)
inverters = df[["plant_id", "source_key"]].drop_duplicates()
full = inverters.merge(pd.DataFrame({"date_time": grid}), how="cross")
full = full.merge(
    df[["source_key", "date_time"]].assign(present=True),
    on=["source_key", "date_time"],
    how="left",
)
missing = full[full["present"].isna()].drop(columns="present").copy()


# Step 3b: was the whole plant silent, or just this inverter? And was it day or night?
# If no inverter of the plant reported, the logger or network was down, which is a data
# problem, not an inverter problem. And a gap at night costs no energy at all.
plant_times = df[["plant_id", "date_time"]].drop_duplicates().assign(plant_reported=True)
missing = missing.merge(plant_times, on=["plant_id", "date_time"], how="left")
missing["plant_wide"] = missing["plant_reported"].isna()
missing["daylight"] = is_daylight(missing["date_time"])


# Step 3c: group back-to-back missing readings into one gap.
# Otherwise an 8-day outage looks like 800 unrelated missing readings.
# If a missing reading comes exactly 15 minutes after the previous one, it belongs to the
# same gap; anything else starts a new gap. cumsum() then numbers the gaps 1, 2, 3, ...
#   13:30 new -> gap 1 | 13:45 -> gap 1 | 14:00 -> gap 1 | 23:00 new -> gap 2 | 23:15 -> gap 2
missing = missing.sort_values(["source_key", "date_time"])
step = missing.groupby("source_key")["date_time"].diff() != pd.Timedelta("15min")
missing["event"] = step.cumsum()

gaps = (
    missing.groupby(["plant_id", "source_key", "event"])
    .agg(
        gap_start=("date_time", "min"),
        gap_end=("date_time", "max"),
        n_intervals=("date_time", "size"),
        daylight_intervals=("daylight", "sum"),
        plant_wide_share=("plant_wide", "mean"),
    )
    .reset_index(drop=False)
    .drop(columns="event")
)
gaps["hours"] = gaps["n_intervals"] * INTERVAL_H

# Label each gap: only this inverter, the whole plant, or a mix of both.
gaps["scope"] = pd.cut(
    gaps["plant_wide_share"], [-0.01, 0.0, 0.999, 1.0],
    labels=["inverter", "mixed", "plant_wide"],
).astype(str)


# Step 3d: did the inverter keep producing while it was silent?
# This is how I found that the four silent Plant 2 inverters were fine: their counters rose
# about 70,000 kWh during the 8.8-day gap, the same as a healthy neighbour. So I compare the
# lifetime counter just before and just after every gap. merge_asof finds the nearest reading
# in time: "backward" = last one before the gap, "forward" = first one after it.
counters = df[["source_key", "date_time", "total_yield"]]

before = pd.merge_asof(
    gaps.sort_values("gap_start"), counters.sort_values("date_time"),
    left_on="gap_start", right_on="date_time", by="source_key",
    direction="backward", allow_exact_matches=False,
)["total_yield"].to_numpy()
gaps = gaps.sort_values("gap_start").reset_index(drop=True)
gaps["total_before"] = before

after = pd.merge_asof(
    gaps.sort_values("gap_end"), counters.sort_values("date_time"),
    left_on="gap_end", right_on="date_time", by="source_key",
    direction="forward", allow_exact_matches=False,
)
gaps = after.drop(columns="date_time").rename(columns={"total_yield": "total_after"})
gaps["counter_increase_kwh"] = gaps["total_after"] - gaps["total_before"]


# Step 3e: give each gap a verdict.
# I only trust the counter if both values look sane (not 0, not going backwards),
# because Plant 2's counters are often broken. The verdicts:
#   night_only_no_energy_impact - the whole gap was at night, nothing lost
#   data_loss_energy_recorded   - daytime gap, but the counter kept rising: only the data is missing
#   possible_outage             - daytime gap and the counter didn't move: energy probably lost
#   unknown                     - counter not usable, needs another check (e.g. compare with neighbours)
valid = (gaps["total_before"] > 0) & (gaps["total_after"] >= gaps["total_before"])

gaps["classification"] = "unknown"
gaps.loc[gaps["daylight_intervals"] == 0, "classification"] = "night_only_no_energy_impact"
gaps.loc[(gaps["daylight_intervals"] > 0) & valid & (gaps["counter_increase_kwh"] > 0),
         "classification"] = "data_loss_energy_recorded"
gaps.loc[(gaps["daylight_intervals"] > 0) & valid & (gaps["counter_increase_kwh"] == 0),
         "classification"] = "possible_outage"

gaps = gaps.drop(columns="plant_wide_share").sort_values(["plant_id", "source_key", "gap_start"])


# --- 4. Save the results ----------------------------------------------------------------
# Drop and rebuild both output tables every time, so the script can be rerun as often
# as I like. That's safe because they're built entirely from the raw tables, which stay untouched.

with engine.begin() as conn:
    conn.execute(text("DROP TABLE IF EXISTS generation_clean, data_gaps;"))
df.to_sql("generation_clean", engine, index=False, chunksize=10_000)
gaps.to_sql("data_gaps", engine, index=False)


# --- 5. Print a summary -----------------------------------------------------------------
# A quick sanity check that the run went as expected. The numbers should match the
# data-quality report: 97.2 % clean rows, 453 gaps, 7,140 missing inverter readings.

print(f"\ngeneration_clean: {len(df):,} rows")
print(df.groupby("plant_id")[flag_cols].sum().T.to_string())
print(f"\nShare of clean rows: {df['is_clean'].mean():.1%}")
print(f"\ndata_gaps: {len(gaps):,} gap events, {gaps['n_intervals'].sum():,} missing inverter-intervals")
print(
    gaps.groupby(["plant_id", "classification"])
    .agg(events=("n_intervals", "size"),
         intervals=("n_intervals", "sum"),
         daylight_intervals=("daylight_intervals", "sum"))
    .to_string()
)
