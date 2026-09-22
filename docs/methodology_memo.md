# Northstar Workforce Model — Methodology and Assumptions

**To:** Engagement delivery team | **Date:** 2026-09-22
**Inputs:** `northstar_census.csv` (as of 2026-08-31), `northstar_pnl_labor.csv` (TTM ended 2026-06-30)
**Reproduce:** `pip install -r requirements.txt && python src/build_model.py`

## What this is

A **point-in-time annual run-rate** for every filled position as of 2026-08-31, at fully loaded cost. Not a forecast and not a restatement of the TTM P&L: anything priced against it is priced at what Northstar pays today, not the twelve-month average. That drives the reconciliation below.

**1,665 employee positions, 1,646.0 FTE, $97.22M annual base, $138.74M fully loaded, 1.427x blended load**, plus 40 contract and temp workers annualized at $3.70M. Position detail, the role-level rollup, department load rates, the P&L bridge and all 1,203 imputations are in `output/`. Mappings live in `config/`, not in code.

## Scope and cleaning

**Duplicates.** Six employee_ids appear twice. In each case one row has a populated `status` and a department consistent with the job title; the twin has a blank `status` and a contradictory department. Keeping the row with a status resolves all six duplicates and all six blank statuses.

**Population.** Active plus Leave (8, flagged) are filled positions — the seat is held and benefits continue. The 100 terminated are excluded; ten lack a termination date, but their `9xxxx` id prefix confirms status. That prefix is a reliable independent signal throughout (`1xxxx` employee, `9xxxx` terminated, `Cxxxx` contract).

**Contract labour is out of the employee model.** The 40 `Cxxxx` workers carry no employer tax or benefit cost, so loading them at employee rates would overstate cost; they belong against the P&L `contract_labor` line. Six Seasonal workers have normal employee ids and stay in.

## Standardization, and the judgment worth challenging

22 raw departments collapse to the 10 P&L departments and 71 raw titles to 44 standardized roles. **The crosswalk keys on department *and* title, because neither alone works.** Pinnacle books 315 field staff under one `Field` department that must be split on title; Great Lakes does the reverse, booking 146 people under the generic title `Technician` across three departments, so there the department sets the trade. **This is the most reviewable decision in the model** — it puts 135 of Pinnacle's 285 active field employees on Install rather than Repair — and it is isolated in `config/department_map.csv` with a note on each affected row.

Level is a separate `role_level` attribute rather than part of the role name, keeping `HVAC Service Tech I/II/III`, `Plumber - Apprentice/Journeyman/Master` and `Electrician (Lvl 1/2/3)` comparable across opcos with different ladder vocabularies. Source `job_level` is 77% blank, so where an opco records no level, level is `Unspecified` rather than guessed.

## Pay normalization and fully loaded cost

`pay_basis` is blank on 467 rows and imputed on magnitude (under $200 hourly); the distribution has a wide empty gap, so nothing is a close call. `scheduled_weekly_hours` is blank on 778 rows and defaults to 40 — only 53 employees genuinely work part time, and all have hours recorded. Twenty-one rates are missing, zero, or outside absolute bounds, including an HR Coordinator at $5,200 annual, and are imputed from the median of the same role **and level** within the same opco. Level matters: pooling apprentice electricians with journeymen priced them at $29/hour instead of $18.

**Two errors absolute bounds cannot catch.** A rate can be plausible for the company and impossible for the role, so each position is also compared to its own role-and-level median. Real within-role spread tops out at 1.8x, then jumps: a Great Lakes technician at $185,000 (3.1x) and a Bayside dispatcher at **$485,000, more than the CEO** (10.5x). Both are repriced from peers, removing $562k of base.

**Load factors** are derived per department from the P&L, running 1.24x in Marketing to 1.44x in Field Repair, with Sales at 1.815x on commissions worth 60% of base and Executive at 1.510x on a 35% bonus. Overtime, commissions, bonus and taxes are applied as a percentage of base. **Benefits are allocated per FTE instead**, because the P&L implies $5.1k–$8.8k per head, a per-person cost; allocating them on base would overcharge a master plumber and undercharge an apprentice by thousands while producing the same department total.

Two cautions. Sales commissions spread evenly across all 120 Sales positions including managers, who almost certainly do not earn at that rate, so `variable_comp_cost` is broken out to re-cut. And `fully_loaded_hourly_cost` uses 2,080 *paid* hours — right for costing a position, wrong for pricing work, since a technician is productive roughly 1,700–1,800 hours after PTO, training and drive time.

## Reconciliation to the P&L

A bridge, not a plug. Each department decomposes exactly into a **volume effect** (census headcount versus TTM average headcount at the P&L rate) and a **rate/mix effect**. Both sides are per head, because `avg_headcount_ttm` is a headcount and not an FTE — pricing volume on FTE manufactures a false variance wherever part-timers sit.

Northstar grew **45 heads**, more than explaining the $1.16M base wage gap; pay per head is flat at −1.6%. Departments are tested against that measured drift rather than an assumed merit rate, at a 5-point tolerance. **Nine of ten pass, none by more than 3 points. Marketing is the exception at +14.3%** — not an error, but a Marketing Director at $140,000 hired 2026-07-13 and a specialist hired 2026-08-03, both after the P&L closed, on a base of 10 people. On total employee cost the model is **$138.74M against $137.03M** ex-contract, **+1.3%**.

**One item to escalate.** Annualizing the 40 contract workers gives $3.70M against $1.78M in the P&L — an implied 48.1% utilization that is *identical in every department that uses contract labour*. Either they are engaged about half the year or the census roster is a point-in-time peak. Do not annualize that line at face value until finance confirms which.

## Limitations and AI use

Load factors are department averages, so a technician earning double the spiffs of a peer is invisible; a payroll register by pay period is the highest-value data request and would fix overtime, commissions and benefits together. Benefit cost is an average per head, not by plan election. Level is inferred from title text, leaving 318 field positions `Unspecified` until HR provides a crosswalk. `work_state` is one state per opco, so geography and opco effects cannot be separated — which matters for Cardinal in Ohio and Kentucky, neither present here.

Cursor with Claude profiled the raw files and drafted the pipeline, crosswalks and this memo. Every mapping, rule and threshold was set deliberately, and three AI-suggested defaults were rejected on inspection: an FTE-based volume effect that manufactured a false 8.7% variance in Customer Care, an imputation that pooled apprentices with journeymen, and absolute-only bounds that let the $485,000 dispatcher through. All three were caught by reading the output, not the code. Twelve assertions in the pipeline exist so the next such error fails loudly.
