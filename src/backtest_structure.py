"""Leave-one-out back-test of the structural estimation method used for Cardinal.

The Cardinal estimate rests on one claim: given only a total headcount, the field
organisation of a residential HVAC and plumbing contractor can be predicted from the
structure of a comparable contractor. That claim is testable on data we already have.

Each Northstar operating company is held out in turn and predicted from the mean
field share of the others, using nothing but its total headcount. The gap between
prediction and truth is the method's error, and it is what the memo quotes instead of
asserting that the method is reliable.

Scenario 2 repeats the test with Northstar Corporate left in the comparison set, which
is the mistake a hurried analyst makes. It is reported because the failure is more
instructive than the success.

Run:
    .venv/bin/python src/backtest_structure.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output"

FIELD_FAMILIES = ("Field - Install", "Field - Service", "Field Leadership")
CORPORATE_OPCO = "Northstar Corporate"


def shares(model: pd.DataFrame, opcos: list[str]) -> pd.Series:
    """Mean field share across a set of opcos, equally weighted.

    Equal weighting, not headcount weighting, because each opco is one observation of
    how a contractor is structured and the largest one should not dominate the comp.
    """
    rows = []
    for o in opcos:
        d = model[model["opco"] == o]
        r = {f: (d["role_family"] == f).sum() / len(d) for f in FIELD_FAMILIES}
        r["Field total"] = sum(r.values())
        rows.append(r)
    return pd.DataFrame(rows).mean()


def run_scenario(model: pd.DataFrame, pool: list[str], targets: list[str], label: str) -> pd.DataFrame:
    rows = []
    for target in targets:
        comp_set = [o for o in pool if o != target]
        pred_shares = shares(model, comp_set)
        actual = model[model["opco"] == target]
        total = len(actual)
        for family in list(FIELD_FAMILIES) + ["Field total"]:
            if family == "Field total":
                truth = actual["role_family"].isin(FIELD_FAMILIES).sum()
            else:
                truth = (actual["role_family"] == family).sum()
            pred = pred_shares[family] * total
            rows.append(
                {
                    "scenario": label,
                    "held_out_opco": target,
                    "comp_set": " + ".join(o.split()[0] for o in comp_set),
                    "role_family": family,
                    "total_headcount_given": total,
                    "predicted": round(pred, 1),
                    "actual": truth,
                    "error": round(pred - truth, 1),
                    "error_pct": round((pred - truth) / truth * 100, 1) if truth else None,
                }
            )
    return pd.DataFrame(rows)


def summarise(bt: pd.DataFrame) -> pd.DataFrame:
    g = (
        bt.assign(abs_err=bt["error_pct"].abs())
        .groupby(["scenario", "role_family"])
        .agg(
            mean_abs_error_pct=("abs_err", "mean"),
            max_abs_error_pct=("abs_err", "max"),
            mean_signed_error_pct=("error_pct", "mean"),
        )
        .round(1)
        .reset_index()
    )
    order = {f: i for i, f in enumerate(list(FIELD_FAMILIES) + ["Field total"])}
    return g.sort_values(["scenario", "role_family"], key=lambda s: s.map(order).fillna(-1))


def main() -> None:
    model = pd.read_csv(OUTPUT / "workforce_model.csv")
    opcos = sorted(o for o in model["opco"].unique() if o != CORPORATE_OPCO)

    clean = run_scenario(model, opcos, opcos, "1. Operating companies only")
    contaminated = run_scenario(
        model, opcos + [CORPORATE_OPCO], opcos, "2. Shared services left in the comp set"
    )
    bt = pd.concat([clean, contaminated], ignore_index=True)
    bt.to_csv(OUTPUT / "backtest_leave_one_out.csv", index=False)

    summary = summarise(bt)
    summary.to_csv(OUTPUT / "backtest_summary.csv", index=False)

    pd.set_option("display.width", 200)
    print("=" * 78)
    print("LEAVE-ONE-OUT BACK-TEST OF THE STRUCTURAL METHOD")
    print("=" * 78)
    print(
        "\nEach opco is predicted from the other opcos' mean field share, given only\n"
        "its total headcount. This is exactly what the Cardinal model does.\n"
    )

    for label in bt["scenario"].unique():
        print("-" * 78)
        print(label)
        print("-" * 78)
        d = bt[(bt["scenario"] == label) & (bt["role_family"] == "Field total")]
        print(
            d[
                [
                    "held_out_opco",
                    "comp_set",
                    "total_headcount_given",
                    "predicted",
                    "actual",
                    "error_pct",
                ]
            ].to_string(index=False)
        )
        print()
        print(summary[summary["scenario"] == label].drop(columns="scenario").to_string(index=False))
        print()

    clean_total = summary[
        (summary["scenario"].str.startswith("1.")) & (summary["role_family"] == "Field total")
    ].iloc[0]
    dirty_total = summary[
        (summary["scenario"].str.startswith("2.")) & (summary["role_family"] == "Field total")
    ].iloc[0]

    print("=" * 78)
    print("WHAT THIS MEANS FOR THE CARDINAL ESTIMATE")
    print("=" * 78)
    print(
        f"\n  Total field headcount is predicted to within {clean_total['mean_abs_error_pct']:.1f}% "
        f"on average, worst case {clean_total['max_abs_error_pct']:.1f}%."
    )
    worst = summary[
        (summary["scenario"].str.startswith("1.")) & (summary["role_family"] != "Field total")
    ].sort_values("mean_abs_error_pct", ascending=False)
    print(
        f"  Splitting that total between families is harder: "
        + ", ".join(
            f"{r['role_family']} {r['mean_abs_error_pct']:.1f}%" for _, r in worst.iterrows()
        )
        + "."
    )
    print(
        f"\n  Leaving shared services in the comp set moves the mean absolute error from "
        f"{clean_total['mean_abs_error_pct']:.1f}% to {dirty_total['mean_abs_error_pct']:.1f}% and "
        f"biases every\n  estimate the same way: {dirty_total['mean_signed_error_pct']:+.1f}% mean "
        f"signed error against {clean_total['mean_signed_error_pct']:+.1f}% on a clean comp set."
    )
    print(
        "  A one-line comp-set error is therefore worth more than every pay assumption\n"
        "  in the model combined, which is why the review checklist leads with it.\n"
    )

    print("OUTPUTS")
    print("-" * 78)
    print("  output/backtest_leave_one_out.csv")
    print("  output/backtest_summary.csv")
    print()

    if clean_total["mean_abs_error_pct"] >= dirty_total["mean_abs_error_pct"]:
        print(
            "FAILED CHECK: the clean comp set did not beat the contaminated one",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
