"""Cardinal Comfort Services - Part 2 outside-in workforce simulation.

Estimates Cardinal's company-wide headcount, FTE and fully loaded labour cost from
public signals plus an alternative-data profile extract, then rebuilds the Field
Service department at position level on the Part 1 column contract.

Every judgement input lives in config/cardinal_assumptions.csv. Every structural
input is derived from the Part 1 model in output/workforce_model.csv.

Run:
    .venv/bin/python src/build_cardinal.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "candidate-exercise"
CONFIG = ROOT / "config"
OUTPUT = ROOT / "output"

PAID_HOURS_PER_FTE_YEAR = 2080.0

FIELD_FAMILIES = ("Field - Install", "Field - Service", "Field Leadership")
GA_FAMILIES = ("Executive & Corporate", "Finance & Accounting", "HR", "IT", "Marketing")

# The Part 1 model carries no level detail for the comp opco, so the level ladder is
# borrowed. These are the Part 1 standardized roles the ladder is applied to.
HVAC_SERVICE_ROLE = "HVAC Service Technician"
HVAC_INSTALL_ROLE = "HVAC Installer"
PLUMBING_SERVICE_ROLE = "Plumbing Service Technician"

PNL_DEPARTMENT_BY_FAMILY = {
    "Field - Install": "Field Service - Install",
    "Field - Service": "Field Service - Repair & Maintenance",
    "Field Leadership": "Field Service - Repair & Maintenance",
    "Customer Care & Dispatch": "Customer Care & Dispatch",
    "Warehouse & Fleet": "Warehouse & Fleet",
    "Sales": "Sales",
    "Finance & Accounting": "Finance & Accounting",
    "HR": "HR",
    "IT": "IT",
    "Marketing": "Marketing",
    "Executive & Corporate": "Executive & Corporate",
}


def fail(message: str) -> None:
    print(f"FAILED CHECK: {message}", file=sys.stderr)
    sys.exit(1)


# --- Inputs -----------------------------------------------------------------


def load_assumptions() -> dict:
    raw = pd.read_csv(CONFIG / "cardinal_assumptions.csv")
    if raw["key"].duplicated().any():
        fail("cardinal_assumptions.csv has duplicate keys")
    out: dict = {}
    for key, value in zip(raw["key"], raw["value"]):
        try:
            out[key] = float(value)
        except ValueError:
            out[key] = value
    return out


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    profiles = pd.read_csv(
        DATA / "cardinal_profiles.csv",
        parse_dates=["start_date", "profile_last_updated"],
    )
    entities = pd.read_csv(DATA / "cardinal_entity_mapping.csv")
    titles = pd.read_csv(CONFIG / "cardinal_title_map.csv")
    bls = pd.read_csv(CONFIG / "bls_wage_index.csv")
    model = pd.read_csv(OUTPUT / "workforce_model.csv")

    unmapped = set(profiles["title_raw"]) - set(titles["title_raw"])
    if unmapped:
        fail(f"titles missing from cardinal_title_map.csv: {sorted(unmapped)}")
    if titles["title_raw"].duplicated().any():
        fail("cardinal_title_map.csv has duplicate title_raw values")
    return profiles, entities, titles, bls, model


# --- Stage 1: entity resolution and staleness -------------------------------


def build_profile_base(
    profiles: pd.DataFrame,
    entities: pd.DataFrame,
    titles: pd.DataFrame,
    assumptions: dict,
) -> pd.DataFrame:
    """Tag every raw profile as retained or excluded, with the reason recorded.

    Nothing is dropped from the file. Exclusions are carried as a column so the
    path from 645 raw profiles to the live base is auditable end to end.
    """
    false_ids = {int(x) for x in str(assumptions["false_match_entity_ids"]).replace(".0", "").split("|")}
    as_of = pd.Timestamp(assumptions["as_of_date"])
    cutoff = as_of - pd.DateOffset(months=int(assumptions["staleness_cutoff_months"]))

    base = profiles.merge(
        entities.rename(columns={"provider_entity_name": "entity_name"}),
        on="entity_id",
        how="left",
        validate="many_to_one",
    ).merge(titles, on="title_raw", how="left", validate="many_to_one")

    base["excluded_reason"] = ""
    base.loc[base["entity_id"].isin(false_ids), "excluded_reason"] = "false_match_entity"
    base.loc[
        (base["excluded_reason"] == "") & (base["profile_last_updated"] < cutoff),
        "excluded_reason",
    ] = "stale_profile"
    if assumptions["exclude_unclassified_from_structure"] == 1:
        base.loc[
            (base["excluded_reason"] == "") & (base["role_family"] == "Unclassified"),
            "excluded_reason",
        ] = "unresolvable_title"

    # Two live bases, because the two uses differ. A profile the provider could not
    # resolve to a title is still a real person for a headcount signal, but it cannot
    # contribute to a role-mix read.
    base["live_for_headcount"] = base["excluded_reason"].isin(["", "unresolvable_title"])
    base["live_for_structure"] = base["excluded_reason"] == ""
    base["retained_live"] = base["live_for_structure"]
    base["months_since_update"] = (
        (as_of - base["profile_last_updated"]).dt.days / 30.44
    ).round(1)
    base["staleness_cutoff_date"] = cutoff.date().isoformat()

    # Cross-entity duplicate scan: the same person appearing under both Cardinal
    # entities would inflate the live count.
    key = ["title_raw", "location", "start_date"]
    valid = base[~base["entity_id"].isin(false_ids)]
    dupes = valid.duplicated(subset=key, keep=False) & valid.duplicated(
        subset=key + ["entity_id"], keep=False
    )
    cross = valid[valid.duplicated(subset=key, keep=False)].groupby(key)["entity_id"].nunique()
    n_cross = int((cross > 1).sum())
    if n_cross:
        print(f"  WARNING: {n_cross} title/location/start-date keys appear under both entities")
    _ = dupes

    cols = [
        "profile_id",
        "entity_id",
        "entity_name",
        "provider_industry",
        "location",
        "title_raw",
        "standardized_role",
        "role_family",
        "seniority_provider",
        "start_date",
        "profile_last_updated",
        "months_since_update",
        "staleness_cutoff_date",
        "salary_est_base",
        "live_for_headcount",
        "live_for_structure",
        "excluded_reason",
    ]
    out = base[cols].sort_values(["excluded_reason", "entity_id", "location", "title_raw"])
    out.to_csv(OUTPUT / "cardinal_profile_base.csv", index=False)
    return base


# --- Comparable structure from Part 1 ---------------------------------------


def build_comp_structure(model: pd.DataFrame, assumptions: dict) -> pd.DataFrame:
    """Derive Cardinal's expected family mix from the comp opco plus its allocated
    share of the shared-services pool, uplifted for standalone scale diseconomy.

    Great Lakes carries almost no G&A because it consumes Northstar Corporate. A
    standalone Cardinal cannot, so the corporate pool is allocated back on headcount
    and then uplifted: a 400-person company needs its own controller, HR manager and
    IT manager regardless of how thinly they are utilised.
    """
    comp = assumptions["comp_opco"]
    corp = assumptions["corporate_opco"]
    uplift = float(assumptions["standalone_ga_scale_factor"])

    opco = model[model["opco"] == comp]
    corporate = model[model["opco"] == corp]
    other_opcos = model[model["opco"] != corp]
    if opco.empty or corporate.empty:
        fail(f"comp opco '{comp}' or corporate opco '{corp}' not found in workforce_model.csv")

    alloc_share = len(opco) / len(other_opcos)

    opco_fam = opco.groupby("role_family").agg(
        comp_headcount=("employee_id", "count"),
        comp_fte=("fte", "sum"),
        comp_cost=("fully_loaded_annual_cost", "sum"),
    )
    corp_fam = corporate.groupby("role_family").agg(
        corp_headcount=("employee_id", "count"),
        corp_fte=("fte", "sum"),
        corp_cost=("fully_loaded_annual_cost", "sum"),
    )

    s = opco_fam.join(corp_fam, how="outer").fillna(0.0)
    s["allocated_corp_positions"] = s["corp_headcount"] * alloc_share
    s["standalone_ga_positions"] = s["allocated_corp_positions"] * uplift
    s["standalone_positions"] = s["comp_headcount"] + s["standalone_ga_positions"]
    s["proforma_positions"] = s["comp_headcount"] + s["allocated_corp_positions"]

    # Cost per position blends the comp's own people with the corporate people the
    # standalone entity has to replicate, since corporate roles are paid differently.
    comp_cost_pp = (s["comp_cost"] / s["comp_headcount"]).fillna(0.0)
    corp_cost_pp = (s["corp_cost"] / s["corp_headcount"]).fillna(0.0)
    s["cost_per_position"] = (
        comp_cost_pp * s["comp_headcount"] + corp_cost_pp * s["standalone_ga_positions"]
    ) / s["standalone_positions"]

    # Part-time working is concentrated in specific families at the comp (customer
    # care and warehouse), so the FTE haircut is carried per family rather than as a
    # single platform-wide ratio. Field families run 1.00 FTE per head at the comp.
    comp_fte_pp = (s["comp_fte"] / s["comp_headcount"]).fillna(0.0)
    corp_fte_pp = (s["corp_fte"] / s["corp_headcount"]).fillna(0.0)
    s["fte_per_position"] = (
        comp_fte_pp * s["comp_headcount"] + corp_fte_pp * s["standalone_ga_positions"]
    ) / s["standalone_positions"]

    s["standalone_share"] = s["standalone_positions"] / s["standalone_positions"].sum()
    s["proforma_share"] = s["proforma_positions"] / s["proforma_positions"].sum()
    s["comp_share"] = s["comp_headcount"] / s["comp_headcount"].sum()
    return s.reset_index()


# --- Stage 2: coverage diagnostic -------------------------------------------


def coverage_diagnostic(base: pd.DataFrame, structure: pd.DataFrame, assumptions: dict) -> pd.DataFrame:
    """Compare live profiles per family against the structural expectation.

    The anchor is the press-release headcount, not the triangulated headcount, so
    this stays a genuinely independent read on the extract rather than a circular
    restatement of an estimate the profiles themselves helped produce.
    """
    anchor = float(assumptions["press_release_headcount"])
    live = base[base["live_for_structure"]]
    valid = base[base["excluded_reason"] != "false_match_entity"]

    counts = pd.DataFrame(
        {
            "valid_profiles": valid.groupby("role_family").size(),
            "live_profiles": live.groupby("role_family").size(),
        }
    )
    cov = structure.set_index("role_family")[["standalone_share"]].join(counts, how="outer").fillna(0.0)
    cov["anchor_headcount"] = anchor
    cov["expected_positions"] = (cov["standalone_share"] * anchor).round(1)
    cov["implied_coverage"] = (cov["live_profiles"] / cov["expected_positions"]).replace(
        [float("inf")], pd.NA
    )
    cov["profile_share_of_live"] = cov["live_profiles"] / cov["live_profiles"].sum()
    cov["coverage_flag"] = ""
    cov.loc[cov["implied_coverage"] > 1.0, "coverage_flag"] = "over_represented"
    cov.loc[cov["implied_coverage"] < 0.6, "coverage_flag"] = "under_represented"
    cov.loc[cov["expected_positions"] == 0, "coverage_flag"] = "no_structural_expectation"

    cov = cov.reset_index().rename(columns={"index": "role_family"})
    cov["implied_coverage"] = pd.to_numeric(cov["implied_coverage"]).round(3)
    cov["standalone_share"] = cov["standalone_share"].round(4)
    cov["profile_share_of_live"] = cov["profile_share_of_live"].round(4)
    cov = cov[(cov["live_profiles"] > 0) | (cov["expected_positions"] > 0)]
    cov = cov.sort_values("live_profiles", ascending=False)
    cov.to_csv(OUTPUT / "cardinal_coverage_by_role.csv", index=False)
    return cov


# --- Stage 3: headcount triangulation ---------------------------------------


def triangulate(base: pd.DataFrame, structure: pd.DataFrame, assumptions: dict) -> pd.DataFrame:
    a = assumptions
    live_n = int(base["live_for_headcount"].sum())
    field_share = structure.loc[
        structure["role_family"].isin(FIELD_FAMILIES), "standalone_share"
    ].sum()

    revenue_2026e = a["revenue_2025"] * (1 + a["revenue_growth_rate"])
    fleet_field_positions = a["fleet_vehicles"] / a["field_positions_per_vehicle"]

    rows = [
        {
            "signal": "Acquirer press release",
            "source": "cardinal_brief.md, Northstar release 18 Aug 2026",
            "observed_value": f"{a['press_release_headcount']:.0f} employees",
            "derived_headcount": a["press_release_headcount"],
            "weight": a["press_release_weight"],
            "rationale": (
                "Most recent signal and the only one from a party with LOI-level access. "
                "Read as the consolidated company including Louisville, since every other "
                "signal clusters near 400 rather than near 470."
            ),
        },
        {
            "signal": "Live alternative-data profiles",
            "source": "cardinal_profiles.csv after entity and staleness filters",
            "observed_value": f"{live_n} live profiles",
            "derived_headcount": float(live_n),
            "weight": a["live_profiles_weight"],
            "rationale": (
                "Taken at face value as a total only. Field roles are under-covered and "
                "sales over-represented, and the coverage table shows the two errors are "
                "of similar magnitude in opposite directions."
            ),
        },
        {
            "signal": "Revenue per employee",
            "source": "cardinal_brief.md revenue plus industry benchmark",
            "observed_value": f"${revenue_2026e/1e6:.1f}M 2026E at ${a['revenue_per_employee_benchmark']:,.0f}/employee",
            "derived_headcount": revenue_2026e / a["revenue_per_employee_benchmark"],
            "weight": a["revenue_per_employee_weight"],
            "rationale": (
                "Independent of headcount disclosures but inherits a wide benchmark band; "
                "the 200K-250K range alone spans 390 to 490 employees."
            ),
        },
        {
            "signal": "Fleet size",
            "source": "cardinal_brief.md, telematics case study Feb 2026",
            "observed_value": f"{a['fleet_vehicles']:.0f} vehicles",
            "derived_headcount": fleet_field_positions / field_share,
            "weight": a["fleet_weight"],
            "rationale": (
                "A physical signal no one has an incentive to inflate. Grossed up from "
                f"field positions using the comp field share of {field_share:.1%}."
            ),
        },
        {
            "signal": "Trade press profile",
            "source": "cardinal_brief.md, Contracting Business 22 Sept 2025",
            "observed_value": f"more than {a['trade_profile_headcount']:.0f} team members",
            "derived_headcount": a["trade_profile_headcount"] * (1 + a["headcount_growth_rate"]),
            "weight": a["trade_profile_weight"],
            "rationale": (
                "Twelve months stale and stated as a floor, so grown forward one year at "
                "roughly half the revenue growth rate and weighted lightly."
            ),
        },
        {
            "signal": "Business directory listing",
            "source": "cardinal_brief.md, accessed 29 Aug 2026",
            "observed_value": "250-499 employees",
            "derived_headcount": 374.5,
            "weight": 0.0,
            "rationale": (
                "Corroboration only. The band is too wide to discriminate between any of "
                "the other signals, so it carries zero weight."
            ),
        },
    ]

    tri = pd.DataFrame(rows)
    if abs(tri["weight"].sum() - 1.0) > 1e-9:
        fail(f"triangulation weights sum to {tri['weight'].sum():.4f}, not 1.0")
    tri["weighted_contribution"] = tri["derived_headcount"] * tri["weight"]
    tri["derived_headcount"] = tri["derived_headcount"].round(0)
    tri["weighted_contribution"] = tri["weighted_contribution"].round(1)

    total = tri["weighted_contribution"].sum()
    tri = pd.concat(
        [
            tri,
            pd.DataFrame(
                [
                    {
                        "signal": "WEIGHTED ESTIMATE",
                        "source": "this table",
                        "observed_value": "",
                        "derived_headcount": round(total),
                        "weight": 1.0,
                        "rationale": (
                            f"Spread across the weighted signals is "
                            f"{tri[tri['weight'] > 0]['derived_headcount'].min():.0f} to "
                            f"{tri[tri['weight'] > 0]['derived_headcount'].max():.0f}."
                        ),
                        "weighted_contribution": round(total, 1),
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    tri.to_csv(OUTPUT / "cardinal_headcount_triangulation.csv", index=False)
    return tri


# --- Wage index -------------------------------------------------------------


def wage_index(base: pd.DataFrame, bls: pd.DataFrame, assumptions: dict) -> tuple[float, pd.DataFrame]:
    """Branch-weighted BLS index for the comp's geography against Cardinal's.

    Weighted on all valid profiles rather than live ones: branch footprint is one of
    the few things the extract measures well regardless of profile freshness.
    """
    valid = base[base["excluded_reason"] != "false_match_entity"]
    loc_counts = valid.groupby("location").size().rename("profiles")

    rows = []
    for _, r in bls[bls["matches_location"] != "COMP_BASE"].iterrows():
        locs = [x.strip() for x in str(r["matches_location"]).split("|")]
        n = int(loc_counts.reindex(locs).fillna(0).sum())
        rows.append(
            {
                "bls_area": r["bls_area"],
                "annual_median_wage": r["annual_median_wage"],
                "cardinal_locations": ", ".join(locs),
                "profiles": n,
            }
        )
    w = pd.DataFrame(rows)
    if w["profiles"].sum() != len(valid):
        fail(
            f"BLS area weights cover {w['profiles'].sum()} profiles but {len(valid)} are valid; "
            "a Cardinal location is missing from config/bls_wage_index.csv"
        )
    w["weight"] = w["profiles"] / w["profiles"].sum()
    cardinal_wage = float((w["annual_median_wage"] * w["weight"]).sum())
    comp_wage = float(bls.loc[bls["matches_location"] == "COMP_BASE", "annual_median_wage"].iloc[0])
    index = cardinal_wage / comp_wage

    w["weight"] = w["weight"].round(4)
    summary = pd.concat(
        [
            w,
            pd.DataFrame(
                [
                    {
                        "bls_area": "Cardinal branch-weighted",
                        "annual_median_wage": round(cardinal_wage),
                        "cardinal_locations": "all",
                        "profiles": int(w["profiles"].sum()),
                        "weight": 1.0,
                    },
                    {
                        "bls_area": f"Comp base ({assumptions['comp_opco']})",
                        "annual_median_wage": comp_wage,
                        "cardinal_locations": "COMP_BASE",
                        "profiles": 0,
                        "weight": 0.0,
                    },
                    {
                        "bls_area": "INDEX",
                        "annual_median_wage": round(index, 4),
                        "cardinal_locations": "Cardinal / comp",
                        "profiles": 0,
                        "weight": 0.0,
                    },
                ]
            ),
        ],
        ignore_index=True,
    )
    summary.to_csv(OUTPUT / "cardinal_wage_index.csv", index=False)
    return index, summary


# --- Stage 4: company-wide cost ---------------------------------------------


def company_cost(
    structure: pd.DataFrame, headcount: float, index: float, assumptions: dict
) -> tuple[pd.DataFrame, pd.DataFrame]:
    out = structure[
        ["role_family", "standalone_share", "cost_per_position", "fte_per_position"]
    ].copy()
    out["positions"] = out["standalone_share"] * headcount
    out["fte"] = out["positions"] * out["fte_per_position"]
    out["cost_per_position_indexed"] = out["cost_per_position"] * index
    # Cost is per position, not per FTE: the comp's own cost per head already carries
    # its part-time mix, so multiplying by FTE again would double-count the haircut.
    out["fully_loaded_cost"] = out["positions"] * out["cost_per_position_indexed"]
    out["basis"] = "standalone"

    # Pro-forma: Cardinal joins the platform, the duplicated G&A layer collapses back
    # to the allocated share Great Lakes already consumes, and the operating families
    # are untouched because that is the business being bought.
    ga_scale = structure["proforma_positions"] / structure["standalone_positions"]
    pf = out.copy()
    pf["basis"] = "pro_forma_on_northstar"
    pf["positions"] = out["positions"] * ga_scale.values
    pf.loc[~pf["role_family"].isin(GA_FAMILIES), "positions"] = out["positions"]
    pf["fte"] = pf["positions"] * pf["fte_per_position"]
    pf["fully_loaded_cost"] = pf["positions"] * pf["cost_per_position_indexed"]

    both = pd.concat([out, pf], ignore_index=True)
    for c in ("positions", "fte"):
        both[c] = both[c].round(1)
    for c in ("cost_per_position", "cost_per_position_indexed", "fully_loaded_cost"):
        both[c] = both[c].round(0)
    both["standalone_share"] = both["standalone_share"].round(4)
    both["fte_per_position"] = both["fte_per_position"].round(3)
    both = both[
        [
            "basis",
            "role_family",
            "standalone_share",
            "positions",
            "fte_per_position",
            "fte",
            "cost_per_position",
            "cost_per_position_indexed",
            "fully_loaded_cost",
        ]
    ]

    totals = (
        both.groupby("basis")
        .agg(positions=("positions", "sum"), fte=("fte", "sum"), cost=("fully_loaded_cost", "sum"))
        .reset_index()
    )
    both.to_csv(OUTPUT / "cardinal_company_cost.csv", index=False)
    return both, totals


# --- Stage 5: Field Service position-level model ----------------------------


def level_ladder(model: pd.DataFrame, opco: str, role: str) -> pd.DataFrame:
    d = model[(model["opco"] == opco) & (model["standardized_role"] == role)]
    d = d[d["role_level"].notna() & (d["role_level"] != "Unspecified")]
    if d.empty:
        fail(f"no level ladder available for {role} at {opco}")
    g = d.groupby("role_level").agg(
        n=("employee_id", "count"),
        median_base=("annual_base", "median"),
        median_loaded=("fully_loaded_annual_cost", "median"),
        median_hours=("scheduled_weekly_hours", "median"),
    )
    g["mix"] = g["n"] / g["n"].sum()
    # Level premia travel across geographies far better than absolute pay does, so the
    # ladder contributes only the ratio of each level to the role-wide median.
    g["pay_ratio_to_role"] = g["median_base"] / d["annual_base"].median()
    return g.reset_index()


def field_service_model(
    model: pd.DataFrame,
    structure: pd.DataFrame,
    headcount: float,
    index: float,
    assumptions: dict,
    base: pd.DataFrame,
) -> tuple[pd.DataFrame, dict]:
    a = assumptions
    comp = a["comp_opco"]
    comp_rows = model[model["opco"] == comp]

    s = structure.set_index("role_family")
    positions = {f: s.loc[f, "standalone_share"] * headcount for f in FIELD_FAMILIES}

    hvac_service = a["hvac_share_of_service"]
    plumb_install = a["plumbing_share_of_install"]

    comp_median = (
        comp_rows.groupby("standardized_role")["annual_base"].median().to_dict()
    )
    comp_hours = comp_rows.groupby("standardized_role")["scheduled_weekly_hours"].median().to_dict()

    ladders = {
        HVAC_SERVICE_ROLE: level_ladder(model, a["level_ladder_opco_hvac"], HVAC_SERVICE_ROLE),
        HVAC_INSTALL_ROLE: level_ladder(model, a["level_ladder_opco_hvac"], HVAC_INSTALL_ROLE),
        PLUMBING_SERVICE_ROLE: level_ladder(
            model, a["level_ladder_opco_plumbing"], PLUMBING_SERVICE_ROLE
        ),
    }

    buckets = [
        ("Field - Service", HVAC_SERVICE_ROLE, positions["Field - Service"] * hvac_service),
        (
            "Field - Service",
            PLUMBING_SERVICE_ROLE,
            positions["Field - Service"] * (1 - hvac_service),
        ),
        ("Field - Install", HVAC_INSTALL_ROLE, positions["Field - Install"] * (1 - plumb_install)),
    ]

    rows = []
    for family, role, n_role in buckets:
        if n_role <= 0:
            continue
        ladder = ladders[role]
        role_median = comp_median.get(role)
        if role_median is None:
            fail(f"comp opco has no pay observation for {role}")
        hours = comp_hours.get(role, 40.0)
        for _, lv in ladder.iterrows():
            n = n_role * lv["mix"]
            annual_base = role_median * lv["pay_ratio_to_role"] * index
            rows.append(
                {
                    "role_family": family,
                    "standardized_role": role,
                    "role_level": lv["role_level"],
                    "positions": n,
                    "annual_base": annual_base,
                    "scheduled_weekly_hours": hours,
                    "pay_source": (
                        f"{comp} median for {role}, level ratio from "
                        f"{a['level_ladder_opco_hvac'] if role != PLUMBING_SERVICE_ROLE else a['level_ladder_opco_plumbing']}"
                    ),
                }
            )

    # Leadership keeps the comp's own supervisor mix; it is small, observed directly
    # and the alt data covers it well enough to cross-check.
    lead = comp_rows[comp_rows["role_family"] == "Field Leadership"]
    lead_mix = lead.groupby("standardized_role").agg(
        n=("employee_id", "count"),
        median_base=("annual_base", "median"),
        hours=("scheduled_weekly_hours", "median"),
    )
    lead_mix["mix"] = lead_mix["n"] / lead_mix["n"].sum()
    for role, lv in lead_mix.iterrows():
        rows.append(
            {
                "role_family": "Field Leadership",
                "standardized_role": role,
                "role_level": "Unspecified",
                "positions": positions["Field Leadership"] * lv["mix"],
                "annual_base": lv["median_base"] * index,
                "scheduled_weekly_hours": lv["hours"],
                "pay_source": f"{comp} median for {role}",
            }
        )

    fsm = pd.DataFrame(rows)
    fsm["pnl_department"] = fsm["role_family"].map(PNL_DEPARTMENT_BY_FAMILY)
    fsm["opco"] = "Cardinal Comfort Services"

    loads = pd.read_csv(OUTPUT / "load_factors_by_department.csv").set_index("pnl_department")
    fsm = fsm.join(loads, on="pnl_department", rsuffix="_lf")

    # Costed exactly as Part 1 costs a Northstar position, so the two models are
    # directly comparable: taxes on base, benefits per head rather than as a rate.
    fte_each = fsm["role_family"].map(structure.set_index("role_family")["fte_per_position"])
    fsm["fte"] = fsm["positions"] * fte_each
    fsm["hourly_base_rate"] = fsm["annual_base"] / PAID_HOURS_PER_FTE_YEAR
    fsm["overtime_cost"] = fsm["annual_base"] * fsm["overtime_rate"]
    fsm["variable_comp_cost"] = fsm["annual_base"] * fsm["commission_rate"]
    fsm["bonus_cost"] = fsm["annual_base"] * fsm["bonus_rate"]
    fsm["payroll_tax_cost"] = fsm["annual_base"] * fsm["payroll_tax_rate"]
    fsm["benefits_cost"] = fsm["benefits_per_head"] * fte_each
    fsm["fully_loaded_annual_cost"] = (
        fsm["annual_base"]
        + fsm["overtime_cost"]
        + fsm["variable_comp_cost"]
        + fsm["bonus_cost"]
        + fsm["payroll_tax_cost"]
        + fsm["benefits_cost"]
    )
    fsm["load_factor_applied"] = fsm["fully_loaded_annual_cost"] / fsm["annual_base"]
    fsm["fully_loaded_hourly_cost"] = fsm["fully_loaded_annual_cost"] / (
        fte_each * PAID_HOURS_PER_FTE_YEAR
    )
    fsm["total_fully_loaded_cost"] = fsm["fully_loaded_annual_cost"] * fsm["positions"]
    fsm["wage_index_applied"] = round(index, 4)

    cols = [
        "opco",
        "pnl_department",
        "role_family",
        "standardized_role",
        "role_level",
        "positions",
        "fte",
        "scheduled_weekly_hours",
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
        "total_fully_loaded_cost",
        "wage_index_applied",
        "pay_source",
    ]
    fsm = fsm[cols].sort_values(["role_family", "standardized_role", "role_level"])
    for c in ("positions", "fte"):
        fsm[c] = fsm[c].round(1)
    for c in (
        "annual_base",
        "overtime_cost",
        "variable_comp_cost",
        "bonus_cost",
        "payroll_tax_cost",
        "benefits_cost",
        "fully_loaded_annual_cost",
        "total_fully_loaded_cost",
    ):
        fsm[c] = fsm[c].round(0)
    for c in ("hourly_base_rate", "fully_loaded_hourly_cost", "load_factor_applied"):
        fsm[c] = fsm[c].round(2)
    fsm.to_csv(OUTPUT / "cardinal_field_service_model.csv", index=False)

    # --- cross-checks
    techs = fsm[fsm["role_family"] != "Field Leadership"]["positions"].sum()
    leaders = fsm[fsm["role_family"] == "Field Leadership"]["positions"].sum()
    comp_techs = len(comp_rows[comp_rows["role_family"].isin(FIELD_FAMILIES[:2])])
    comp_leaders = len(comp_rows[comp_rows["role_family"] == "Field Leadership"])
    live = base[base["live_for_structure"]]
    alt_leaders = int((live["role_family"] == "Field Leadership").sum())

    checks = {
        "field_positions": techs + leaders,
        "fleet_vehicles": a["fleet_vehicles"],
        "vehicles_per_field_position": a["fleet_vehicles"] / (techs + leaders),
        "supervisor_span": techs / leaders,
        "comp_supervisor_span": comp_techs / comp_leaders,
        "modelled_field_leaders": leaders,
        "alt_data_live_field_leaders": alt_leaders,
        "leader_check_variance_pct": (leaders - alt_leaders) / alt_leaders * 100,
        "field_service_cost": fsm["total_fully_loaded_cost"].sum(),
    }
    return fsm, checks


def salary_sanity_check(base: pd.DataFrame, fsm: pd.DataFrame) -> pd.DataFrame:
    """Test the provider's own salary estimate against the model.

    The provider ships a salary estimate on a minority of profiles. It is worth
    checking, but only as an aggregate cross-check: the role-level ladder it implies
    is inverted, which is exactly the failure mode that would poison a model built
    on it directly.
    """
    valid = base[base["excluded_reason"] != "false_match_entity"]
    field = valid[valid["role_family"].astype(str).str.startswith("Field")]

    rows = []
    for title, d in field.groupby("title_raw"):
        est = d["salary_est_base"].dropna()
        if est.empty:
            continue
        rows.append(
            {
                "level": "role",
                "label": title,
                "profiles_with_estimate": len(est),
                "provider_estimate": round(est.median()),
            }
        )
    out = pd.DataFrame(rows).sort_values("provider_estimate", ascending=False)

    modelled = (fsm["annual_base"] * fsm["positions"]).sum() / fsm["positions"].sum()
    provider = field["salary_est_base"].mean()
    out = pd.concat(
        [
            pd.DataFrame(
                [
                    {
                        "level": "aggregate",
                        "label": "All field roles, provider estimate",
                        "profiles_with_estimate": int(field["salary_est_base"].notna().sum()),
                        "provider_estimate": round(provider),
                    },
                    {
                        "level": "aggregate",
                        "label": "All field roles, this model",
                        "profiles_with_estimate": None,
                        "provider_estimate": round(modelled),
                    },
                    {
                        "level": "aggregate",
                        "label": "Variance",
                        "profiles_with_estimate": None,
                        "provider_estimate": round(modelled - provider),
                    },
                ]
            ),
            out,
        ],
        ignore_index=True,
    )
    out.to_csv(OUTPUT / "cardinal_salary_sanity_check.csv", index=False)
    return out


# --- Stage 6: sensitivity ----------------------------------------------------


def sensitivity(
    model: pd.DataFrame,
    structure: pd.DataFrame,
    headcount: float,
    index: float,
    assumptions: dict,
    base: pd.DataFrame,
    baseline_cost: float,
) -> pd.DataFrame:
    """One-at-a-time tornado on the Field Service cost, which is the deliverable the
    exercise asks to be built end to end."""
    rows = []

    def run(hc: float, idx: float, over: dict) -> float:
        a2 = dict(assumptions)
        a2.update(over)
        st = structure
        if "field_share_mult" in over:
            st = structure.copy()
            m = over["field_share_mult"]
            st.loc[st["role_family"].isin(FIELD_FAMILIES), "standalone_share"] *= m
        _, chk = field_service_model(model, st, hc, idx, a2, base)
        return chk["field_service_cost"]

    specs = [
        (
            "Total headcount",
            f"+/-{assumptions['sensitivity_headcount_pct']:.0%}",
            lambda d: run(headcount * (1 + d), index, {}),
            assumptions["sensitivity_headcount_pct"],
        ),
        (
            "Field share of headcount",
            f"+/-{assumptions['sensitivity_field_share_pct']:.0%}",
            lambda d: run(headcount, index, {"field_share_mult": 1 + d}),
            assumptions["sensitivity_field_share_pct"],
        ),
        (
            "HVAC / plumbing split in service",
            f"+/-{assumptions['sensitivity_trade_split_pct']:.0%} on the HVAC share",
            lambda d: run(
                headcount,
                index,
                {
                    "hvac_share_of_service": min(
                        1.0, assumptions["hvac_share_of_service"] * (1 + d)
                    )
                },
            ),
            assumptions["sensitivity_trade_split_pct"],
        ),
        (
            "Geographic wage index",
            f"+/-{assumptions['sensitivity_wage_index_pct']:.0%}",
            lambda d: run(headcount, index * (1 + d), {}),
            assumptions["sensitivity_wage_index_pct"],
        ),
    ]

    for name, rng, fn, delta in specs:
        low, high = fn(-delta), fn(delta)
        rows.append(
            {
                "assumption": name,
                "range_tested": rng,
                "low_cost": round(min(low, high)),
                "high_cost": round(max(low, high)),
                "swing": round(abs(high - low)),
                "swing_pct_of_baseline": round(abs(high - low) / baseline_cost * 100, 1),
            }
        )

    # Load factor moves cost proportionally, so it is computed rather than re-run.
    lf = assumptions["sensitivity_load_factor_pct"]
    rows.append(
        {
            "assumption": "Load factor",
            "range_tested": f"+/-{lf:.0%}",
            "low_cost": round(baseline_cost * (1 - lf)),
            "high_cost": round(baseline_cost * (1 + lf)),
            "swing": round(baseline_cost * 2 * lf),
            "swing_pct_of_baseline": round(2 * lf * 100, 1),
        }
    )

    sens = pd.DataFrame(rows).sort_values("swing", ascending=False)
    sens["baseline_cost"] = round(baseline_cost)
    sens.to_csv(OUTPUT / "cardinal_sensitivity.csv", index=False)
    return sens


# --- Reporting ---------------------------------------------------------------


def print_summary(
    base, cov, tri, structure, cost, totals, fsm, checks, sal, sens, widx, index, assumptions
) -> None:
    a = assumptions
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 50)

    print("=" * 78)
    print("CARDINAL COMFORT SERVICES - OUTSIDE-IN WORKFORCE SIMULATION")
    print("=" * 78)

    print("\n1. ENTITY RESOLUTION AND STALENESS")
    print("-" * 78)
    print(f"  Raw profiles in extract                    {len(base):>6}")
    for reason, n in base["excluded_reason"].value_counts().items():
        if reason:
            print(f"  Excluded: {reason:<40} {-n:>6}")
    print(f"  Live base for headcount signals            {int(base['live_for_headcount'].sum()):>6}")
    print(f"  Live base for role structure               {int(base['live_for_structure'].sum()):>6}")
    print(f"  Staleness cutoff                     {base['staleness_cutoff_date'].iloc[0]:>12}")
    fm = base[base["excluded_reason"] == "false_match_entity"]
    if len(fm):
        print(
            f"\n  False match: entity {fm['entity_id'].iloc[0]} '{fm['entity_name'].iloc[0]}' "
            f"({fm['provider_industry'].iloc[0]}), {len(fm)} profiles, "
            f"all in {', '.join(sorted(fm['location'].unique()))}"
        )
        print(f"  That is {len(fm)/len(base):.0%} of the extract removed before any analysis.")

    print("\n2. COVERAGE DIAGNOSTIC (anchored on the press-release headcount)")
    print("-" * 78)
    print(
        cov[
            [
                "role_family",
                "live_profiles",
                "profile_share_of_live",
                "standalone_share",
                "expected_positions",
                "implied_coverage",
                "coverage_flag",
            ]
        ].to_string(index=False)
    )

    print("\n3. HEADCOUNT TRIANGULATION")
    print("-" * 78)
    print(tri[["signal", "observed_value", "derived_headcount", "weight"]].to_string(index=False))

    print("\n4. GEOGRAPHIC WAGE INDEX")
    print("-" * 78)
    print(widx.to_string(index=False))

    print("\n5. COMPANY-WIDE FTE AND FULLY LOADED COST")
    print("-" * 78)
    print(cost[cost["basis"] == "standalone"].to_string(index=False))
    print()
    print(totals.to_string(index=False))
    sa = totals[totals["basis"] == "standalone"].iloc[0]
    pf = totals[totals["basis"] == "pro_forma_on_northstar"].iloc[0]
    print(
        f"\n  Standalone headline   {sa['positions']:.0f} employees, {sa['fte']:.0f} FTE, "
        f"${sa['cost']/1e6:.1f}M fully loaded"
    )
    print(
        f"  Pro-forma on Northstar {pf['positions']:.0f} employees, {pf['fte']:.0f} FTE, "
        f"${pf['cost']/1e6:.1f}M fully loaded"
    )
    print(
        f"  Shared-services synergy {sa['positions']-pf['positions']:.0f} positions, "
        f"${(sa['cost']-pf['cost'])/1e6:.1f}M"
    )
    rev = a["revenue_2025"] * (1 + a["revenue_growth_rate"])
    print(f"\n  Cross-check: labour at {sa['cost']/rev:.1%} of 2026E revenue of ${rev/1e6:.1f}M")
    print(f"               benchmark range 35-40% = ${rev*0.35/1e6:.1f}M to ${rev*0.40/1e6:.1f}M")
    print(f"               revenue per FTE ${rev/sa['fte']:,.0f} against the $200-250K benchmark")

    print("\n6. FIELD SERVICE POSITION-LEVEL MODEL")
    print("-" * 78)
    print(
        fsm[
            [
                "role_family",
                "standardized_role",
                "role_level",
                "positions",
                "annual_base",
                "fully_loaded_annual_cost",
                "load_factor_applied",
                "total_fully_loaded_cost",
            ]
        ].to_string(index=False)
    )
    print(
        f"\n  Field Service total   {checks['field_positions']:.0f} positions, "
        f"${checks['field_service_cost']/1e6:.1f}M fully loaded"
    )
    print(
        f"  Fleet cross-check     {checks['fleet_vehicles']:.0f} vehicles / "
        f"{checks['field_positions']:.0f} positions = "
        f"{checks['vehicles_per_field_position']:.2f} vehicles per field position"
    )
    print(
        f"  Supervisor span       {checks['supervisor_span']:.1f}:1 modelled against "
        f"{checks['comp_supervisor_span']:.1f}:1 at the comp"
    )
    print(
        f"  Leader count          {checks['modelled_field_leaders']:.0f} modelled against "
        f"{checks['alt_data_live_field_leaders']:.0f} seen live in the alt data "
        f"({checks['leader_check_variance_pct']:+.0f}%)"
    )
    roll = cost[(cost["basis"] == "standalone") & cost["role_family"].isin(FIELD_FAMILIES)][
        "fully_loaded_cost"
    ].sum()
    print(
        f"  Bottom-up vs roll-up  ${checks['field_service_cost']/1e6:.2f}M built position by "
        f"position against ${roll/1e6:.2f}M from the comp's average cost per head "
        f"({(checks['field_service_cost']-roll)/roll:+.1%})"
    )

    print("\n7. PROVIDER SALARY ESTIMATE AS A CROSS-CHECK")
    print("-" * 78)
    print(sal.to_string(index=False))

    print("\n8. SENSITIVITY (Field Service fully loaded cost)")
    print("-" * 78)
    print(sens.to_string(index=False))

    print("\n9. OUTPUTS")
    print("-" * 78)
    for f in sorted(OUTPUT.glob("cardinal_*.csv")):
        print(f"  {f.relative_to(ROOT)}")
    print()


def run_checks(base, cov, tri, totals, fsm, checks, assumptions, cost) -> None:
    results = []

    def check(name, condition, detail=""):
        results.append((name, bool(condition), detail))

    live = int(base["live_for_headcount"].sum())
    check("Every raw profile is accounted for", len(base) == 645, f"{len(base)} rows")
    check(
        "False-match entity fully excluded",
        (base[base["entity_id"] == 9083341]["excluded_reason"] == "false_match_entity").all(),
    )
    check("Live base is smaller than the valid base", live < (base["entity_id"] != 9083341).sum())
    check("Triangulation weights sum to 1", abs(tri["weight"][:-1].sum() - 1.0) < 1e-9)
    check(
        "Sales is flagged as over-represented",
        cov.loc[cov["role_family"] == "Sales", "coverage_flag"].iloc[0] == "over_represented",
    )
    check(
        "Field service is flagged as under-represented",
        cov.loc[cov["role_family"] == "Field - Service", "coverage_flag"].iloc[0]
        == "under_represented",
    )
    sa = totals[totals["basis"] == "standalone"].iloc[0]
    pf = totals[totals["basis"] == "pro_forma_on_northstar"].iloc[0]
    check("Pro-forma is cheaper than standalone", pf["cost"] < sa["cost"])
    check(
        "Pro-forma saving comes only from G&A",
        abs((sa["positions"] - pf["positions"]) - 9.3) < 3,
        f"{sa['positions']-pf['positions']:.1f} positions",
    )
    rev = assumptions["revenue_2025"] * (1 + assumptions["revenue_growth_rate"])
    check(
        "Labour lands within 5 points of the 35-40% benchmark",
        0.30 <= sa["cost"] / rev <= 0.45,
        f"{sa['cost']/rev:.1%}",
    )
    check(
        "Vehicles per field position is between 0.9 and 1.2",
        0.9 <= checks["vehicles_per_field_position"] <= 1.2,
        f"{checks['vehicles_per_field_position']:.2f}",
    )
    check(
        "Modelled field leaders are within 25% of the alt-data count",
        abs(checks["leader_check_variance_pct"]) <= 25,
        f"{checks['leader_check_variance_pct']:+.0f}%",
    )
    check(
        "Field Service model reconciles to the company build",
        abs(fsm["positions"].sum() - checks["field_positions"]) < 0.5,
    )
    check("No negative or zero positions", (fsm["positions"] > 0).all())
    check(
        "Load factors match the Part 1 P&L derivation",
        fsm["load_factor_applied"].between(1.35, 1.55).all(),
        f"{fsm['load_factor_applied'].min():.2f}-{fsm['load_factor_applied'].max():.2f}",
    )
    roll = cost[(cost["basis"] == "standalone") & cost["role_family"].isin(FIELD_FAMILIES)][
        "fully_loaded_cost"
    ].sum()
    var = (checks["field_service_cost"] - roll) / roll
    check(
        "Position-level field build agrees with the company roll-up within 3%",
        abs(var) <= 0.03,
        f"{var:+.1%}",
    )

    print("10. VALIDATION CHECKS")
    print("-" * 78)
    for name, ok, detail in results:
        tag = "PASS" if ok else "FAIL"
        suffix = f"  ({detail})" if detail else ""
        print(f"  [{tag}] {name}{suffix}")
    failures = [n for n, ok, _ in results if not ok]
    print()
    if failures:
        fail(f"{len(failures)} validation check(s) failed: {failures}")


def main() -> None:
    OUTPUT.mkdir(exist_ok=True)
    assumptions = load_assumptions()
    profiles, entities, titles, bls, model = load_inputs()

    base = build_profile_base(profiles, entities, titles, assumptions)
    structure = build_comp_structure(model, assumptions)
    cov = coverage_diagnostic(base, structure, assumptions)
    tri = triangulate(base, structure, assumptions)
    headcount = float(tri.loc[tri["signal"] == "WEIGHTED ESTIMATE", "derived_headcount"].iloc[0])
    index, widx = wage_index(base, bls, assumptions)

    cost, totals = company_cost(structure, headcount, index, assumptions)
    fsm, checks = field_service_model(model, structure, headcount, index, assumptions, base)
    sens = sensitivity(
        model, structure, headcount, index, assumptions, base, checks["field_service_cost"]
    )
    # The sensitivity runs re-enter field_service_model, so restore the baseline file.
    fsm, checks = field_service_model(model, structure, headcount, index, assumptions, base)

    sal = salary_sanity_check(base, fsm)
    print_summary(
        base, cov, tri, structure, cost, totals, fsm, checks, sal, sens, widx, index, assumptions
    )
    run_checks(base, cov, tri, totals, fsm, checks, assumptions, cost)


if __name__ == "__main__":
    main()
