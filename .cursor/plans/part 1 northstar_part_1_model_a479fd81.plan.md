---
name: Northstar Part 1 Model
overview: Build a reproducible Python pipeline that turns the raw Northstar census into a position-level workforce model at fully loaded cost, with load factors derived from the department P&L and a variance bridge that reconciles the point-in-time run-rate to TTM actuals.
todos:
  - id: env
    content: Set up .venv with pandas, add requirements.txt
    status: completed
  - id: crosswalks
    content: Build config/department_map.csv and config/role_map.csv keyed on (raw department, raw job title), covering the Pinnacle Field split and the Great Lakes generic Technician title
    status: completed
  - id: clean
    content: "Write the clean/dedupe/scope stage: dedupe on populated status, scope to Active plus Leave, separate the 40 Cxxxx contract workers, log terminated-without-date rows"
    status: completed
  - id: normalize
    content: "Normalize pay: impute pay_basis by magnitude threshold, default weekly hours to 40, impute zero/blank/implausible pay rates from role-within-opco medians, compute FTE and annual base, emit exceptions.csv"
    status: completed
  - id: loadfactors
    content: Derive per-department load factors from the P&L (percent-of-base for OT, commissions, bonus, taxes; per-FTE for benefits) and apply to every position
    status: completed
  - id: model
    content: Emit output/workforce_model.csv with standardized role, FTE, annual base, fully loaded annual cost, fully loaded hourly cost
    status: completed
  - id: recon
    content: Build output/reconciliation_by_department.csv as a bridge from TTM P&L to census run-rate with a 5 percent residual tolerance flag
    status: completed
  - id: checks
    content: Add the assertion suite (unmapped values, duplicates, totals tie, loaded cost >= base)
    status: completed
  - id: memo
    content: Write docs/methodology_memo.md, two pages max
    status: completed
isProject: false
---

= Part 1 — Northstar Census Onboarding

## Deliverables

- `src/build_model.py` — single reproducible pipeline, raw CSV in, outputs out
- `config/role_map.csv`, `config/department_map.csv` — editable crosswalks (raw title/department to standardized role/P&L department) so the delivery team can change mappings without touching code
- `output/workforce_model.csv` — one row per active position: employee_id, opco, standardized_role, role_family, pnl_department, work_state, fte, annual_base, fully_loaded_annual_cost, fully_loaded_hourly_cost, plus the cost components and a data-quality flag column
- `output/reconciliation_by_department.csv` — census run-rate vs P&L, with the bridge lines
- `output/exceptions.csv` — every row where an assumption was imputed, so the CFO can audit
- `docs/methodology_memo.md` — two pages max, written for the delivery team
- Environment: `pandas` is not installed (`python3` 3.12.6, no venv). Create `.venv` and `pip install pandas`, and pin it in `requirements.txt`.

## What the data actually looks like

1,811 rows, 1,805 unique employee_ids, 4 opcos plus corporate, 22 raw departments, 77 raw job titles, 4 work states (one per opco: FL Bayside, TX Pinnacle, MI Great Lakes, AZ Redwood; corporate is FL).

The employee_id suffix is a reliable independent signal and should be used to cross-check `status`: `1xxxx` = employee (1,657 Active, 8 Leave, 6 blank status), `9xxxx` = terminated (all 100), `Cxxxx` = non-employee worker (40, all 1099/Contractor/Temp).

## Pipeline steps

### 1. Dedupe
Six employee_ids appear twice (`BAY-10405`, `RED-10236`, `GLC-10345`, `RED-10009`, `GLC-10138`, `RED-10139`). In every case one row has a populated `status` and the correct department, the twin has blank `status` and a department that contradicts the job title (an `Apprentice Electrician` filed under `Parts & Fleet`). Rule: keep the row with populated `status`; this resolves all six duplicates and all six blank statuses at once.

### 2. Scope to active positions
Keep `Active` and `Leave` (8 people; positions are filled and still carry benefit cost — flagged with `on_leave = TRUE` so the team can drop them). Exclude the 100 terminated. Ten terminated rows carry no `termination_date`; the `9xxxx` prefix confirms the status, log them to exceptions rather than treating as active.

Non-employee workers (40 `Cxxxx` rows) get `worker_class = Contract` and are held in a separate output section: they belong against the P&L `contract_labor` line ($1,778,460), not the employee load factors. Six `Seasonal` workers carry normal `1xxxx` IDs and stay in the employee population.

### 3. Standardize department and role
22 raw departments collapse to the 10 P&L departments. Most are direct (`Acctg`/`Finance`/`Finance & Accounting` to Finance & Accounting; `Call Center`/`CSR`/`Customer Care` to Customer Care & Dispatch; `Warehouse`/`Fleet`/`Parts & Fleet` to Warehouse & Fleet).

The one real judgment call: Pinnacle's single `Field` department (315 people) has to be split across `Field Service - Install` and `Field Service - Repair & Maintenance` on job title — `Plumbing Installer*` and `Installation Manager` to Install, `Plumber - *`, `Field Supervisor`, `Service Manager` to Repair. Conversely, Great Lakes uses a generic `Technician` title (146 people) across Install, Service - HVAC, and Service - Plumbing, so there the department decides the trade discipline, not the title. The crosswalk therefore keys on (raw department, raw job title), not either alone.

Role standardization covers the obvious collisions (`CSR`/`Cust Svc Rep`/`Customer Service Rep`/`Customer Service Representative`, `Install Mgr`/`Install Manager`/`Installation Manager`, `Dispacher` typo) and preserves level where the title carries it (`HVAC Service Tech I/II/III`, `Lvl 1/2/3`, Apprentice/Journeyman/Master). `job_level` is 77% blank so it is a supporting attribute, not the level source.

### 4. Normalize pay to annual base and FTE
- `pay_basis` is blank for 467 rows (almost all Pinnacle). Impute by magnitude: rate under $200 is Hourly (387 rows), $200 or more is Annual (80 rows). The gap in the distribution is wide — blank-basis hourly values top out well under $200 and the annual ones start in the tens of thousands — so the rule is unambiguous. Every imputation is logged.
- `scheduled_weekly_hours` is blank for 778 rows; default to 40 and flag. Only 60 people genuinely work part-time (42 in Customer Care, 14 in Warehouse, all with hours recorded), so FTE = hours / 40 and total FTE lands at 1,686 against 1,705 headcount.
- Five rows have `pay_rate` of 0.0 and 15 have it blank. Impute from the median rate of the same standardized role within the same opco, flag as imputed. One row (`RED-10277`, HR Coordinator, $5,200 Annual) is an implausible annual figure — treat it the same way and flag it.
- Annual base = hourly rate x scheduled hours x 52, or annual rate x FTE.

### 5. Derive load factors from the P&L
The P&L supports clean per-department rates on base wages. Computed from the file:

- Field Install: OT 12.1%, commissions/spiffs 8.1%, bonus 1.0%, taxes 8.5%, benefits 13.1% ($7,714/head), total load 1.428x
- Field Repair: OT 11.9%, commissions 10.0%, bonus 1.0%, taxes 8.5%, benefits 13.0% ($8,262/head), total load 1.444x
- Sales: commissions 60.1% of base, bonus 2.0%, load 1.815x
- Customer Care 1.265x, Warehouse & Fleet 1.296x, Finance 1.265x, HR 1.245x, IT 1.265x, Marketing 1.236x, Executive 1.510x
- Blended employee load factor, excluding contract labor: 1.426x

Two allocation choices that matter and belong in the memo: benefits are allocated per FTE (they run $5.1k–$8.8k per head within a department and are a per-person cost, so a percent-of-base allocation would overcharge senior people and undercharge apprentices), while OT, commissions, bonus, and payroll taxes are allocated as a percent of base. Both methods reproduce the same department total; the per-head benefits treatment gives a more defensible position-level number. Sales commissions at 60% of base is the extreme case — for Sales the model should show base and variable separately so nobody mistakes the loaded figure for salary.

Fully loaded hourly cost = fully loaded annual / (FTE x 2,080). The memo should note that 2,080 is a paid-hours denominator, and that a billable or productive-hours denominator (roughly 1,700–1,800 for field techs after PTO, training, and drive time) is the right basis for pricing work, not for costing a position.

### 6. Reconcile with a bridge, do not force-fit
Prototype run of the census against the P&L (census annualized base vs P&L base wages):

- Field Install: 493 HC / 493 FTE vs 473 TTM avg HC; $28.87M vs $27.88M (1.04x)
- Field Repair: 621 / 621 vs 583; $38.89M vs $36.91M (1.05x)
- Sales: 120 vs 119; $6.24M vs $6.33M (0.98x)
- Customer Care: 213 HC / 198.6 FTE vs 202; $9.00M vs $8.51M (1.06x)
- Warehouse & Fleet: 100 / 95.3 vs 94; $4.24M vs $4.16M (1.02x)
- Finance 60 vs 59 (0.98x), HR 28 vs 28 (0.98x), IT 36 vs 31 (1.28x), Marketing 12 vs 10 (1.33x), Executive 22 vs 21 (1.00x)
- Total: 1,705 HC / 1,686 FTE vs 1,620 TTM avg HC; $100.3M vs $96.1M (1.04x)

The reconciliation output presents this as a bridge rather than a plug, because the two sources measure different things: the census is a point-in-time run-rate at 2026-08-31, the P&L is a TTM average through 2026-06-30. Bridge lines per department: TTM P&L base, plus headcount growth (census FTE vs TTM average headcount, priced at average department rate), plus 2 months of timing and merit drift, plus contract labor reclassified out, equals expected census run-rate; residual is the unexplained variance. Flag any department where the residual exceeds 5% of base. IT and Marketing will fail that test — IT because contract labor is 9.8% of its total cost and Marketing because it grew from 10 to 12 heads on a small base — and the memo names both explicitly rather than burying them.

## Memo outline (two pages)

1. What the model is and what it is not (point-in-time run-rate, not a forecast; excludes contract labor from employee cost)
2. Decision log: the dedupe rule, the Leave inclusion, the Pinnacle Field split, the pay_basis imputation threshold, the benefits-per-head allocation, the 2,080-hour denominator
3. Reconciliation result and the two departments that miss tolerance, with the reason for each
4. Known limitations and what would resolve them (payroll register by pay period, benefit election detail, a title-to-level crosswalk from HR)
5. How AI tools were used

## Sanity checks to build into the script

Assert no duplicate employee_ids in output; assert every raw department and job title maps to exactly one target (fail loudly on an unmapped new value); assert modeled department totals equal the sum of position rows; assert fully loaded cost is always greater than or equal to base; assert every imputed field appears in `exceptions.csv`.