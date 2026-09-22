"""Northstar Home Services Group - Part 1 position-level workforce model.

Reads the raw census and department labor P&L, produces a position-level model at
fully loaded cost, a reconciliation to the P&L by department, and an exception log.

Run:
    .venv/bin/python src/build_model.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "candidate-exercise"
CONFIG = ROOT / "config"
OUTPUT = ROOT / "output"

# --- Documented assumptions -------------------------------------------------
CENSUS_AS_OF = pd.Timestamp("2026-08-31")
PNL_PERIOD_END = pd.Timestamp("2026-06-30")
WEEKS_PER_YEAR = 52
FULL_TIME_WEEKLY_HOURS = 40.0
PAID_HOURS_PER_FTE_YEAR = 2080.0

# Blank pay_basis is imputed on magnitude. No hourly rate in the file approaches
# this threshold and no annual salary falls below it, so the split is unambiguous.
HOURLY_ANNUAL_SPLIT = 200.0

# Rates outside these bounds are treated as source-system errors, not real pay.
MIN_PLAUSIBLE_HOURLY = 7.25
MAX_PLAUSIBLE_HOURLY = 200.0
MIN_PLAUSIBLE_ANNUAL = 25_000.0
MAX_PLAUSIBLE_ANNUAL = 1_000_000.0

# Absolute bounds miss errors that are plausible for a company but not for a role,
# such as a dispatcher recorded above the CEO. Observed within-role spread in this
# census tops out at 1.8x the role median, so anything beyond these multiples of the
# peer median is a source error rather than a well paid incumbent.
PEER_OUTLIER_HIGH = 2.5
PEER_OUTLIER_LOW = 0.4
MIN_PEERS_FOR_OUTLIER_TEST = 5

# Departments whose rate/mix variance deviates from the platform-wide rate/mix
# variance by more than this are flagged for review.
RATE_MIX_TOLERANCE = 0.05

ACTIVE_STATUSES = ("Active", "Leave")

exceptions: list[dict] = []


def log_exception(row: pd.Series, field: str, issue: str, original, resolved, rule: str) -> None:
    exceptions.append(
        {
            "employee_id": row["employee_id"],
            "opco": row["opco"],
            "raw_department": row["department"],
            "raw_job_title": row["job_title"],
            "field": field,
            "issue": issue,
            "original_value": original,
            "resolved_value": resolved,
            "rule_applied": rule,
        }
    )


# --- 1. Load ----------------------------------------------------------------


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    census = pd.read_csv(
        DATA / "northstar_census.csv",
        dtype={"employee_id": "string", "job_level": "string"},
        parse_dates=["hire_date", "termination_date"],
    )
    for col in ["opco", "department", "job_title", "employee_type", "pay_basis", "status", "work_state"]:
        census[col] = census[col].fillna("").str.strip()

    pnl = pd.read_csv(DATA / "northstar_pnl_labor.csv")
    # keep_default_na keeps the literal "NA" role_level (meaning "no level ladder for
    # this role") from being read as a missing value and silently dropped by groupby.
    dept_map = pd.read_csv(CONFIG / "department_map.csv", keep_default_na=False)
    role_map = pd.read_csv(CONFIG / "role_map.csv", keep_default_na=False)
    return census, pnl, dept_map, role_map


# --- 2. Dedupe and scope ----------------------------------------------------


def dedupe(census: pd.DataFrame) -> pd.DataFrame:
    """Six employee_ids appear twice. In every case one row carries a populated
    status and a department consistent with the job title, and the twin carries a
    blank status and a contradictory department. Keep the row with a status."""
    dup_ids = census.loc[census["employee_id"].duplicated(keep=False), "employee_id"].unique()
    keep = census["status"] != ""
    dropped = census[census["employee_id"].isin(dup_ids) & ~keep]
    for _, row in dropped.iterrows():
        log_exception(
            row,
            "employee_id",
            "Duplicate employee_id",
            f"{row['department']} / status blank",
            "row dropped",
            "Keep the duplicate row with a populated status",
        )
    deduped = census[~(census["employee_id"].isin(dup_ids) & ~keep)].copy()
    still_dup = deduped["employee_id"].duplicated().sum()
    if still_dup:
        raise ValueError(f"{still_dup} duplicate employee_ids survived the dedupe rule")
    return deduped


def classify_workers(df: pd.DataFrame) -> pd.DataFrame:
    """The employee_id suffix is an independent signal of worker class and status:
    1xxxx = employee, 9xxxx = terminated, Cxxxx = contract or temp worker."""
    suffix = df["employee_id"].str.split("-").str[1].str[0]
    df = df.assign(
        id_class=suffix.map({"1": "Employee", "9": "Terminated", "C": "Contract"}).fillna("Unknown"),
        worker_class=lambda d: d["id_class"].where(d["id_class"] == "Contract", "Employee"),
        on_leave=df["status"] == "Leave",
    )

    unknown = df[df["id_class"] == "Unknown"]
    for _, row in unknown.iterrows():
        log_exception(row, "employee_id", "Unrecognised id prefix", row["employee_id"], "treated as Employee", "id suffix 1/9/C")

    # Terminated rows missing a termination_date: the 9xxxx prefix confirms status.
    missing_term = df[(df["status"] == "Terminated") & df["termination_date"].isna()]
    for _, row in missing_term.iterrows():
        log_exception(
            row,
            "termination_date",
            "Terminated with no termination_date",
            "blank",
            "excluded from active model",
            "9xxxx id prefix corroborates terminated status",
        )

    conflict = df[(df["id_class"] == "Terminated") & (df["status"].isin(ACTIVE_STATUSES))]
    if len(conflict):
        raise ValueError(f"{len(conflict)} rows have a terminated id prefix but an active status")
    return df


def scope_active(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    active = df[df["status"].isin(ACTIVE_STATUSES)].copy()
    counts = {
        "rows_in": len(df),
        "terminated_excluded": int((df["status"] == "Terminated").sum()),
        "active_positions": len(active),
        "of_which_on_leave": int(active["on_leave"].sum()),
        "of_which_contract": int((active["worker_class"] == "Contract").sum()),
    }
    return active, counts


# --- 3. Standardize department and role -------------------------------------


def validate_crosswalks(dept_map: pd.DataFrame, role_map: pd.DataFrame) -> None:
    key = ["raw_department", "raw_job_title"]
    for name, table in (("department_map", dept_map), ("role_map", role_map)):
        dupes = table[table.duplicated(key, keep=False)]
        if len(dupes):
            raise ValueError(f"config/{name}.csv has repeated keys:\n{dupes[key].to_string(index=False)}")

    only_dept = set(map(tuple, dept_map[key].values)) - set(map(tuple, role_map[key].values))
    only_role = set(map(tuple, role_map[key].values)) - set(map(tuple, dept_map[key].values))
    if only_dept or only_role:
        raise ValueError(f"Crosswalks disagree. Only in department_map: {sorted(only_dept)}. Only in role_map: {sorted(only_role)}")

    split_family = role_map.groupby("standardized_role")["role_family"].nunique()
    if (split_family > 1).any():
        offenders = split_family[split_family > 1].index.tolist()
        raise ValueError(f"A standardized role maps to more than one role family: {offenders}")


def apply_crosswalks(df: pd.DataFrame, dept_map: pd.DataFrame, role_map: pd.DataFrame) -> pd.DataFrame:
    validate_crosswalks(dept_map, role_map)
    key = ["department", "job_title"]
    out = df.merge(
        dept_map.rename(columns={"raw_department": "department", "raw_job_title": "job_title"}),
        on=key,
        how="left",
    ).merge(
        role_map.rename(columns={"raw_department": "department", "raw_job_title": "job_title"}),
        on=key,
        how="left",
    )

    unmapped = out[out["pnl_department"].isna() | out["standardized_role"].isna()]
    if len(unmapped):
        pairs = unmapped[key].drop_duplicates().to_string(index=False)
        raise ValueError(
            "Unmapped (department, job_title) combinations. Add them to "
            f"config/department_map.csv and config/role_map.csv:\n{pairs}"
        )

    out["role_with_level"] = out.apply(
        lambda r: r["standardized_role"] if r["role_level"] in ("NA", "") else f"{r['standardized_role']} - {r['role_level']}",
        axis=1,
    )
    return out


# --- 4. Normalize pay and FTE -----------------------------------------------


def normalize_pay(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # FTE from scheduled hours; blank means the source HRIS does not carry the field.
    hours_missing = df["scheduled_weekly_hours"].isna()
    for _, row in df[hours_missing].iterrows():
        log_exception(row, "scheduled_weekly_hours", "Blank scheduled hours", "blank", FULL_TIME_WEEKLY_HOURS, "Default to 40 hours per week")
    df["scheduled_weekly_hours"] = df["scheduled_weekly_hours"].fillna(FULL_TIME_WEEKLY_HOURS)
    df["hours_imputed"] = hours_missing
    df["fte"] = (df["scheduled_weekly_hours"] / FULL_TIME_WEEKLY_HOURS).round(4)

    # Pay basis: use what the HRIS carries, otherwise infer from magnitude.
    basis_missing = df["pay_basis"] == ""
    inferred = pd.Series("", index=df.index, dtype="object")
    inferred[basis_missing & (df["pay_rate"] < HOURLY_ANNUAL_SPLIT)] = "Hourly"
    inferred[basis_missing & (df["pay_rate"] >= HOURLY_ANNUAL_SPLIT)] = "Annual"
    df["pay_basis_resolved"] = df["pay_basis"].where(~basis_missing, inferred)
    df["pay_basis_imputed"] = basis_missing

    for _, row in df[basis_missing & (df["pay_basis_resolved"] != "")].iterrows():
        log_exception(
            row,
            "pay_basis",
            "Blank pay basis",
            row["pay_rate"],
            row["pay_basis_resolved"],
            f"Rate below {HOURLY_ANNUAL_SPLIT:.0f} is Hourly, at or above is Annual",
        )

    # Rates that are missing, zero, or outside plausible bounds are source errors.
    rate = df["pay_rate"]
    basis = df["pay_basis_resolved"]
    df["pay_rate_imputed"] = (
        rate.isna()
        | ((basis == "Hourly") & ((rate < MIN_PLAUSIBLE_HOURLY) | (rate > MAX_PLAUSIBLE_HOURLY)))
        | ((basis == "Annual") & ((rate < MIN_PLAUSIBLE_ANNUAL) | (rate > MAX_PLAUSIBLE_ANNUAL)))
        | (basis == "")
    )

    def annualize(frame: pd.DataFrame) -> pd.Series:
        is_hourly = frame["pay_basis_resolved"] == "Hourly"
        return (
            (frame["pay_rate"] * frame["scheduled_weekly_hours"] * WEEKS_PER_YEAR)
            .where(is_hourly, frame["pay_rate"] * frame["fte"])
            .round(2)
        )

    def impute_from_peers(targets: pd.Index, issue: str | None, distrust_basis: bool) -> None:
        """Replace each target's pay rate with a peer median, narrowest peer group
        first. Level matters inside the trades, where an apprentice and a master
        plumber share a standardized role. Peers exclude rows already known to be bad."""
        valid = df[~df["pay_rate_imputed"]]
        peer_groups = [
            (["opco", "standardized_role", "role_level", "pay_basis_resolved"], "median of same role and level within opco"),
            (["opco", "standardized_role", "pay_basis_resolved"], "median of same role within opco"),
            (["standardized_role", "role_level", "pay_basis_resolved"], "median of same role and level across all opcos"),
            (["standardized_role", "pay_basis_resolved"], "median of same role across all opcos"),
        ]
        peer_medians = [(valid.groupby(keys)["pay_rate"].median(), keys, label) for keys, label in peer_groups]
        modal_basis = valid.groupby(["opco", "standardized_role"])["pay_basis_resolved"].agg(
            lambda s: s.mode().iat[0] if len(s.mode()) else "Hourly"
        )

        for idx in targets:
            row = df.loc[idx].copy()
            # A blank basis, or a basis attached to a value we do not believe, is
            # itself suspect, so fall back to what this role's peers are paid on.
            if row["pay_basis_resolved"] == "" or distrust_basis:
                resolved_basis = modal_basis.get((row["opco"], row["standardized_role"]), "Hourly")
                if resolved_basis != row["pay_basis_resolved"]:
                    df.loc[idx, "pay_basis_imputed"] = True
                row["pay_basis_resolved"] = resolved_basis
                df.loc[idx, "pay_basis_resolved"] = resolved_basis

            median, source = None, None
            for medians, keys, label in peer_medians:
                candidate = medians.get(tuple(row[k] for k in keys))
                if candidate is not None and not pd.isna(candidate):
                    median, source = candidate, label
                    break
            if median is None:
                raise ValueError(f"No peer rate available to impute {row['employee_id']} ({row['standardized_role']})")

            original = "blank" if pd.isna(row["pay_rate"]) else row["pay_rate"]
            row_issue = issue or ("Blank pay rate" if pd.isna(row["pay_rate"]) else "Implausible pay rate")
            log_exception(row, "pay_rate", row_issue, original, round(float(median), 2), source)
            df.loc[idx, "pay_rate"] = float(median)

    impute_from_peers(df.index[df["pay_rate_imputed"]], issue=None, distrust_basis=False)
    df["annual_base"] = annualize(df)

    # Absolute bounds cannot catch a rate that is plausible for the company but not
    # for the role, such as a dispatcher recorded above the CEO. Compare every
    # position to the median of its own role and level.
    base_per_fte = df["annual_base"] / df["fte"]
    group = [df["standardized_role"], df["role_level"]]
    ratio_to_peers = base_per_fte / base_per_fte.groupby(group).transform("median")
    peer_outlier = (
        (base_per_fte.groupby(group).transform("count") >= MIN_PEERS_FOR_OUTLIER_TEST)
        & ((ratio_to_peers > PEER_OUTLIER_HIGH) | (ratio_to_peers < PEER_OUTLIER_LOW))
        & ~df["pay_rate_imputed"]
    )
    if peer_outlier.any():
        df.loc[peer_outlier, "pay_rate_imputed"] = True
        impute_from_peers(
            df.index[peer_outlier],
            issue=f"Pay outside {PEER_OUTLIER_LOW:g}x-{PEER_OUTLIER_HIGH:g}x of the role and level median",
            distrust_basis=True,
        )
        df["annual_base"] = annualize(df)

    df["hourly_base_rate"] = (df["annual_base"] / (df["fte"] * PAID_HOURS_PER_FTE_YEAR)).round(2)
    df["data_quality_flag"] = df.apply(
        lambda r: ";".join(
            f
            for f, on in (
                ("hours_defaulted", r["hours_imputed"]),
                ("pay_basis_imputed", r["pay_basis_imputed"]),
                ("pay_rate_imputed", r["pay_rate_imputed"]),
                ("on_leave", r["on_leave"]),
            )
            if on
        )
        or "clean",
        axis=1,
    )
    return df


# --- 5. Load factors from the P&L -------------------------------------------


def derive_load_factors(pnl: pd.DataFrame) -> pd.DataFrame:
    f = pnl.copy()
    base = f["base_wages_salaries"]
    f["overtime_rate"] = f["overtime"] / base
    f["commission_rate"] = f["commissions_spiffs"] / base
    f["bonus_rate"] = f["bonus"] / base
    f["payroll_tax_rate"] = f["payroll_taxes"] / base
    f["benefits_rate_of_base"] = f["benefits"] / base
    f["benefits_per_head"] = f["benefits"] / f["avg_headcount_ttm"]
    f["load_factor_pnl"] = (f["total_labor_cost"] - f["contract_labor"]) / base
    return f[
        [
            "pnl_department",
            "overtime_rate",
            "commission_rate",
            "bonus_rate",
            "payroll_tax_rate",
            "benefits_rate_of_base",
            "benefits_per_head",
            "load_factor_pnl",
            "base_wages_salaries",
            "total_labor_cost",
            "contract_labor",
            "avg_headcount_ttm",
        ]
    ]


def apply_load_factors(df: pd.DataFrame, factors: pd.DataFrame) -> pd.DataFrame:
    out = df.merge(factors, on="pnl_department", how="left", validate="many_to_one")
    out["overtime_cost"] = (out["annual_base"] * out["overtime_rate"]).round(2)
    out["variable_comp_cost"] = (out["annual_base"] * out["commission_rate"]).round(2)
    out["bonus_cost"] = (out["annual_base"] * out["bonus_rate"]).round(2)
    out["payroll_tax_cost"] = (out["annual_base"] * out["payroll_tax_rate"]).round(2)
    # Benefits are a per-person cost, not a function of pay, so they are allocated
    # per FTE rather than as a percentage of base.
    out["benefits_cost"] = (out["benefits_per_head"] * out["fte"]).round(2)

    out["fully_loaded_annual_cost"] = (
        out["annual_base"]
        + out["overtime_cost"]
        + out["variable_comp_cost"]
        + out["bonus_cost"]
        + out["payroll_tax_cost"]
        + out["benefits_cost"]
    ).round(2)
    out["load_factor_applied"] = (out["fully_loaded_annual_cost"] / out["annual_base"]).round(4)
    out["fully_loaded_hourly_cost"] = (
        out["fully_loaded_annual_cost"] / (out["fte"] * PAID_HOURS_PER_FTE_YEAR)
    ).round(2)
    return out


def price_contract_workers(df: pd.DataFrame) -> pd.DataFrame:
    """Contract and temp workers carry no employer taxes or benefits, so they are
    priced at their contracted rate and reconciled to the P&L contract_labor line."""
    out = df.copy()
    out["annualized_contract_cost"] = out["annual_base"]
    return out[
        [
            "employee_id",
            "opco",
            "pnl_department",
            "standardized_role",
            "role_level",
            "role_family",
            "employee_type",
            "work_state",
            "fte",
            "pay_rate",
            "pay_basis_resolved",
            "annualized_contract_cost",
            "data_quality_flag",
        ]
    ].sort_values(["pnl_department", "standardized_role", "employee_id"])


# --- 6. Reconciliation -------------------------------------------------------


def reconcile(model: pd.DataFrame, contract: pd.DataFrame, factors: pd.DataFrame) -> pd.DataFrame:
    agg = (
        model.groupby("pnl_department")
        .agg(
            model_headcount=("employee_id", "count"),
            model_fte=("fte", "sum"),
            model_annual_base=("annual_base", "sum"),
            model_fully_loaded_cost=("fully_loaded_annual_cost", "sum"),
        )
        .reset_index()
    )
    contract_agg = (
        contract.groupby("pnl_department")
        .agg(model_contract_headcount=("employee_id", "count"), model_contract_annualized=("annualized_contract_cost", "sum"))
        .reset_index()
    )

    r = factors.merge(agg, on="pnl_department", how="outer").merge(contract_agg, on="pnl_department", how="left")
    r[["model_contract_headcount", "model_contract_annualized"]] = r[
        ["model_contract_headcount", "model_contract_annualized"]
    ].fillna(0)

    r = r.rename(
        columns={
            "base_wages_salaries": "pnl_base_wages_ttm",
            "avg_headcount_ttm": "pnl_avg_headcount_ttm",
            "total_labor_cost": "pnl_total_labor_cost_ttm",
            "contract_labor": "pnl_contract_labor_ttm",
        }
    )
    r["pnl_employee_labor_cost_ttm"] = r["pnl_total_labor_cost_ttm"] - r["pnl_contract_labor_ttm"]

    # Exact volume / rate decomposition of the base wage gap between the TTM P&L
    # and the point-in-time census run-rate. Volume + rate always equals the total.
    # Both sides are measured per head: avg_headcount_ttm is a headcount, not an FTE,
    # so pricing the volume effect on FTE would manufacture a rate variance in the
    # two departments that carry part-time staff.
    pnl_base_per_head = r["pnl_base_wages_ttm"] / r["pnl_avg_headcount_ttm"]
    model_base_per_head = r["model_annual_base"] / r["model_headcount"]
    headcount_variance = r["model_headcount"] - r["pnl_avg_headcount_ttm"]

    r["pnl_base_per_head"] = pnl_base_per_head.round(0)
    r["model_base_per_head"] = model_base_per_head.round(0)
    r["model_base_per_fte"] = (r["model_annual_base"] / r["model_fte"]).round(0)
    r["headcount_variance"] = headcount_variance
    r["headcount_variance_pct"] = (headcount_variance / r["pnl_avg_headcount_ttm"]).round(4)
    r["fte_variance_vs_ttm_headcount"] = (r["model_fte"] - r["pnl_avg_headcount_ttm"]).round(1)

    r["base_variance"] = (r["model_annual_base"] - r["pnl_base_wages_ttm"]).round(0)
    r["bridge_volume_effect"] = (headcount_variance * pnl_base_per_head).round(0)
    r["bridge_rate_mix_effect"] = (r["model_headcount"] * (model_base_per_head - pnl_base_per_head)).round(0)
    r["rate_mix_pct_of_base"] = (r["bridge_rate_mix_effect"] / r["pnl_base_wages_ttm"]).round(4)

    # Wage drift between the TTM midpoint and the census date is real and is not a
    # modelling error, so the tolerance test is against the platform-wide drift
    # measured from these same two files rather than against an assumed merit rate.
    platform_rate_mix = r["bridge_rate_mix_effect"].sum() / r["pnl_base_wages_ttm"].sum()
    r["platform_rate_mix_pct"] = round(platform_rate_mix, 4)
    r["deviation_from_platform_pct"] = (r["rate_mix_pct_of_base"] - platform_rate_mix).round(4)
    r["within_tolerance"] = r["deviation_from_platform_pct"].abs() <= RATE_MIX_TOLERANCE

    r["loaded_cost_variance"] = (r["model_fully_loaded_cost"] - r["pnl_employee_labor_cost_ttm"]).round(0)
    r["loaded_cost_variance_pct"] = (r["loaded_cost_variance"] / r["pnl_employee_labor_cost_ttm"]).round(4)
    r["contract_utilization_implied"] = (
        r["pnl_contract_labor_ttm"] / r["model_contract_annualized"].where(r["model_contract_annualized"] > 0)
    ).round(3)

    cols = [
        "pnl_department",
        "model_headcount",
        "model_fte",
        "pnl_avg_headcount_ttm",
        "headcount_variance",
        "headcount_variance_pct",
        "fte_variance_vs_ttm_headcount",
        "model_annual_base",
        "pnl_base_wages_ttm",
        "base_variance",
        "bridge_volume_effect",
        "bridge_rate_mix_effect",
        "rate_mix_pct_of_base",
        "platform_rate_mix_pct",
        "deviation_from_platform_pct",
        "within_tolerance",
        "model_base_per_head",
        "model_base_per_fte",
        "pnl_base_per_head",
        "load_factor_pnl",
        "model_fully_loaded_cost",
        "pnl_employee_labor_cost_ttm",
        "loaded_cost_variance",
        "loaded_cost_variance_pct",
        "model_contract_headcount",
        "model_contract_annualized",
        "pnl_contract_labor_ttm",
        "contract_utilization_implied",
    ]
    return r[cols].sort_values("pnl_department").reset_index(drop=True)


# --- 7. Checks ---------------------------------------------------------------


def run_checks(model: pd.DataFrame, contract: pd.DataFrame, recon: pd.DataFrame, exc: pd.DataFrame, counts: dict) -> list[str]:
    checks = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        checks.append(f"{'PASS' if condition else 'FAIL'}  {name}{(' - ' + detail) if detail and not condition else ''}")
        if not condition:
            raise AssertionError(f"{name}: {detail}")

    all_positions = pd.concat([model["employee_id"], contract["employee_id"]])
    check("No duplicate employee_id in output", all_positions.duplicated().sum() == 0)
    check(
        "Employee model plus contract roster equals the active population",
        len(model) + len(contract) == counts["active_positions"],
        f"{len(model)} + {len(contract)} != {counts['active_positions']}",
    )
    check("No contract worker leaked into the employee model", (model["worker_class"] == "Employee").all())
    check("Every position has a standardized role", model["standardized_role"].notna().all() and (model["standardized_role"] != "").all())
    check("Every position maps to a P&L department", model["pnl_department"].isin(recon["pnl_department"]).all())
    check("Annual base is positive", (model["annual_base"] > 0).all())
    check("FTE within (0, 1]", ((model["fte"] > 0) & (model["fte"] <= 1)).all())
    check("Fully loaded cost >= annual base", (model["fully_loaded_annual_cost"] >= model["annual_base"]).all())

    cost_components = (
        model["annual_base"]
        + model["overtime_cost"]
        + model["variable_comp_cost"]
        + model["bonus_cost"]
        + model["payroll_tax_cost"]
        + model["benefits_cost"]
    )
    check(
        "Cost components sum to fully loaded cost",
        bool((cost_components - model["fully_loaded_annual_cost"]).abs().max() < 0.01),
    )

    dept_totals = model.groupby("pnl_department")["fully_loaded_annual_cost"].sum().round(2)
    recon_totals = recon.set_index("pnl_department")["model_fully_loaded_cost"].round(2)
    check(
        "Department totals tie to the sum of position rows",
        bool(dept_totals.sub(recon_totals, fill_value=0).abs().max() < 0.01),
    )
    bridge_gap = (recon["bridge_volume_effect"] + recon["bridge_rate_mix_effect"] - recon["base_variance"]).abs().max()
    check(
        "Bridge decomposition is exact (volume + rate = total variance)",
        bool(bridge_gap <= 5),
        f"largest gap ${bridge_gap:,.2f} exceeds rounding tolerance",
    )

    imputed = model[model["data_quality_flag"].str.contains("imputed|defaulted", regex=True)]["employee_id"]
    logged = set(exc["employee_id"]) if len(exc) else set()
    check(
        "Every imputed position appears in exceptions.csv",
        set(imputed).issubset(logged),
        f"{len(set(imputed) - logged)} missing",
    )
    return checks


# --- 8. Orchestration --------------------------------------------------------


MODEL_COLUMNS = [
    "employee_id",
    "opco",
    "pnl_department",
    "raw_department",
    "standardized_role",
    "role_level",
    "role_with_level",
    "role_family",
    "raw_job_title",
    "worker_class",
    "employee_type",
    "work_state",
    "hire_date",
    "tenure_years",
    "fte",
    "scheduled_weekly_hours",
    "pay_basis_resolved",
    "pay_rate",
    "annual_base",
    "hourly_base_rate",
    "overtime_cost",
    "variable_comp_cost",
    "bonus_cost",
    "payroll_tax_cost",
    "benefits_cost",
    "fully_loaded_annual_cost",
    "fully_loaded_hourly_cost",
    "load_factor_applied",
    "data_quality_flag",
]


def main() -> int:
    OUTPUT.mkdir(exist_ok=True)
    census, pnl, dept_map, role_map = load_inputs()

    deduped = dedupe(census)
    classified = classify_workers(deduped)
    active, counts = scope_active(classified)
    mapped = apply_crosswalks(active, dept_map, role_map)
    normalized = normalize_pay(mapped)

    normalized["tenure_years"] = ((CENSUS_AS_OF - normalized["hire_date"]).dt.days / 365.25).round(2)
    normalized = normalized.rename(columns={"department": "raw_department", "job_title": "raw_job_title"})

    employees = normalized[normalized["worker_class"] == "Employee"].copy()
    contractors = normalized[normalized["worker_class"] == "Contract"].copy()

    factors = derive_load_factors(pnl)
    model = apply_load_factors(employees, factors)
    contract = price_contract_workers(contractors)
    recon = reconcile(model, contract, factors)

    exc = pd.DataFrame(exceptions)
    checks = run_checks(model, contract, recon, exc, counts)

    model_out = model[MODEL_COLUMNS].sort_values(["pnl_department", "standardized_role", "employee_id"])
    model_out.to_csv(OUTPUT / "workforce_model.csv", index=False)
    contract.to_csv(OUTPUT / "contract_labor.csv", index=False)
    recon.to_csv(OUTPUT / "reconciliation_by_department.csv", index=False)
    exc.to_csv(OUTPUT / "exceptions.csv", index=False)

    by_role = (
        model.groupby(["pnl_department", "standardized_role", "role_level"], dropna=False)
        .agg(
            headcount=("employee_id", "count"),
            fte=("fte", "sum"),
            annual_base=("annual_base", "sum"),
            fully_loaded_annual_cost=("fully_loaded_annual_cost", "sum"),
            avg_fully_loaded_cost_per_fte=("fully_loaded_annual_cost", "sum"),
        )
        .reset_index()
    )
    by_role["avg_fully_loaded_cost_per_fte"] = (by_role["fully_loaded_annual_cost"] / by_role["fte"]).round(0)
    by_role["avg_fully_loaded_hourly_cost"] = (by_role["avg_fully_loaded_cost_per_fte"] / PAID_HOURS_PER_FTE_YEAR).round(2)
    by_role.sort_values(["pnl_department", "standardized_role", "role_level"]).to_csv(
        OUTPUT / "model_by_role.csv", index=False
    )

    factors.round(4).to_csv(OUTPUT / "load_factors_by_department.csv", index=False)

    print_summary(counts, model, contract, recon, exc, checks)
    return 0


def print_summary(counts, model, contract, recon, exc, checks) -> None:
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 40)

    print("=" * 96)
    print(f"Northstar workforce model - census as of {CENSUS_AS_OF.date()}, P&L TTM ended {PNL_PERIOD_END.date()}")
    print("=" * 96)
    print("\nScope")
    for k, v in counts.items():
        print(f"  {k.replace('_', ' '):28s} {v:>8,}")
    print(f"  {'employee positions modelled':28s} {len(model):>8,}")
    print(f"  {'total FTE':28s} {model['fte'].sum():>8,.1f}")
    print(f"  {'exception rows logged':28s} {len(exc):>8,}")

    print("\nCost summary (employees, annual run-rate)")
    print(f"  Annual base                  ${model['annual_base'].sum():>14,.0f}")
    print(f"  Fully loaded cost            ${model['fully_loaded_annual_cost'].sum():>14,.0f}")
    print(f"  Blended load factor           {model['fully_loaded_annual_cost'].sum() / model['annual_base'].sum():>14.3f}x")
    print(f"  Contract labour (annualized) ${contract['annualized_contract_cost'].sum():>14,.0f} across {len(contract)} workers")

    print("\nReconciliation to P&L by department: TTM base wages bridged to census run-rate")
    view = recon[
        [
            "pnl_department",
            "model_headcount",
            "model_fte",
            "pnl_avg_headcount_ttm",
            "pnl_base_wages_ttm",
            "bridge_volume_effect",
            "bridge_rate_mix_effect",
            "model_annual_base",
            "deviation_from_platform_pct",
            "within_tolerance",
        ]
    ].copy()
    for c in ["model_annual_base", "pnl_base_wages_ttm", "bridge_volume_effect", "bridge_rate_mix_effect"]:
        view[c] = view[c].map(lambda v: f"{v/1e6:>6,.2f}M")
    view["deviation_from_platform_pct"] = view["deviation_from_platform_pct"].map(lambda v: f"{v:+.1%}")
    view["model_fte"] = view["model_fte"].round(1)
    print(view.to_string(index=False))
    print(f"\n  Platform-wide rate/mix drift between the TTM midpoint and the census date: "
          f"{recon['platform_rate_mix_pct'].iat[0]:+.1%} of base")

    failed = recon[~recon["within_tolerance"]]
    if len(failed):
        print(f"  Departments deviating from that by more than {RATE_MIX_TOLERANCE:.0%}: "
              f"{', '.join(failed['pnl_department'])}")
    else:
        print(f"  No department deviates from that by more than {RATE_MIX_TOLERANCE:.0%}.")

    print("\nChecks")
    for c in checks:
        print(f"  {c}")
    print(f"\nOutputs written to {OUTPUT}")


if __name__ == "__main__":
    sys.exit(main())
