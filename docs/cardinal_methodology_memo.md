# Cardinal Comfort Services — Outside-In Workforce Simulation

**To:** Engagement delivery team | **Date:** 2026-09-22
**Inputs:** `cardinal_brief.md`, `cardinal_profiles.csv`, `cardinal_entity_mapping.csv`, the Part 1 model in `output/workforce_model.csv`, BLS OEWS May 2025
**Reproduce:** `pip install -r requirements.txt && python src/build_cardinal.py && python src/backtest_structure.py`

## What this is, and the one number to read first

An estimate of Cardinal's workforce built without a data room, priced on the same basis as the Part 1 model so the two can be added together. Every figure comes out of `src/build_cardinal.py`, every judgement input sits in `config/cardinal_assumptions.csv`, and the method's error has been measured rather than asserted.

**Headline: 403 employees, 392 FTE, $34.0M fully loaded annual labour cost, standalone.** Field Service is 257 of those positions at $22.9M, built role by role and level by level in `output/cardinal_field_service_model.csv`.

The highest-impact step is in none of that. It is that **22% of the alternative-data extract is not Cardinal.** Entity `9083341` "Cardinal Comfort Solutions" contributes 140 profiles, all in Florida, under an HVAC *wholesale distribution* business at `cardinalsupplyco.com` — different name, state, industry and domain from the Cincinnati contractor. The titles settle it: eight of its nine (Counter Sales Associate, Inside Sales – HVAC Parts, Delivery Driver, Pricing Analyst) appear nowhere in the other two entities, and no residential contractor runs a parts counter. Taking the provider's match at face value inflates the profile base 28%.

## 1. Company-wide FTE and fully loaded labour cost

### From 645 profiles to a defensible base

Nothing is deleted. Every profile carries an `excluded_reason` in `output/cardinal_profile_base.csv`, so the path from raw extract to working base is auditable.

| Step | Profiles | Reason |
|---|---:|---|
| Raw extract | 645 | Three provider entities |
| Less false-match entity | −140 | Florida wholesale distributor, see above |
| Less stale profiles | −125 | Not updated since 2024-09-01 |
| **Live base for headcount** | **380** | |
| Less unresolvable titles | −22 | "Team Member", "Associate", "Consultant", "Intern" |
| **Live base for role structure** | **358** | |

"Current" profiles are not current: `profile_last_updated` runs from 2018 to 2026, with 125 last touched in 2022 or earlier and none at all in 2023. The 24-month cutoff is a judgement and the config entry most worth flexing. Two live bases are deliberate — a profile the provider could not resolve to a title is still a real person for a headcount signal, but cannot contribute to a role-mix read.

### Coverage is role-dependent, and that is the central methodological point

Anchoring on the press-release headcount of 400 — an external number, so this stays an independent read — gives the extract's implied coverage. The largest families, with the full table in `output/cardinal_coverage_by_role.csv`:

| Role family | Live profiles | Expected positions | Implied coverage |
|---|---:|---:|---:|
| Sales | 77 | 21.8 | 3.53x |
| Field – Service | 60 | 133.9 | 0.45x |
| Customer Care & Dispatch | 54 | 52.2 | 1.03x |
| Executive & Corporate | 41 | 6.9 | 5.94x |
| Field – Install | 28 | 100.6 | 0.28x |
| Field Leadership | 18 | 20.9 | 0.86x |
| Warehouse & Fleet | 15 | 27.5 | 0.55x |

Field installers appear at roughly a quarter of their true numbers; sales at three and a half times. This is not noise, it is who maintains a professional profile. **The naive read — 380 profiles as a headcount and their mix as a structure — is wrong in both directions at once, and because the errors partly cancel on the total, it looks defensible.** That is what makes it dangerous. Everything below uses the extract only where it is demonstrably strong (branch footprint, the supervisory layer, trade vocabulary) and takes role structure from a comparable company instead.

### Triangulation

| Signal | Observed | Implies | Weight |
|---|---|---:|---:|
| Acquirer press release, Aug 2026 | ~400 employees | 400 | 0.40 |
| Live alternative-data profiles | 380 live | 380 | 0.20 |
| Revenue per employee | $97.7M 2026E at $225K | 434 | 0.20 |
| Fleet size, Feb 2026 | 260 vehicles | 407 | 0.15 |
| Trade press profile, Sept 2025 | >350 team members | 374 | 0.05 |
| Business directory | 250–499 | — | 0.00 |
| **Weighted estimate** | | **403** | **1.00** |

The press release carries the heaviest weight for recency and LOI-level access. Revenue per employee is genuinely independent but inherits a wide band — the $200–250K benchmark alone spans 390 to 490 employees. The fleet figure is the one signal nobody has an incentive to inflate, grossed up using the comp's field share. The directory band is too wide to discriminate between the others, so it is shown at zero weight rather than quietly dropped.

**Louisville is the live judgement.** Cardinal Heating & Air was acquired in March 2024 with roughly 60 employees and appears as 105 valid profiles across both Cardinal entities. The press release says "approximately 400 employees across six branches", and Louisville is a seventh location under its own name; if 400 excludes it, the consolidated company is nearer 470. This memo takes the inclusive reading because the four signals independent of the press release cluster at 374–434, not near 470. **It is worth one question on the first management call** — getting it wrong moves the answer about 17%.

### Cost, standalone and pro-forma

Structure comes from Great Lakes Comfort Systems: 392 employees running HVAC plus plumbing against Cardinal at roughly 400 running HVAC plus plumbing, as close a structural comp as this platform contains. Great Lakes carries almost no G&A because it consumes Northstar Corporate shared services, so the corporate pool is allocated back on headcount (19.5 positions) and uplifted 1.5x. **That uplift is the largest judgement in the cost build**: a 400-person standalone company needs a controller, an HR manager and an IT manager whether or not it can keep them busy. Cost per position is the comp's own fully loaded cost per head, so Cardinal is priced on exactly the P&L-derived load factors Northstar's CFO has already seen.

|  | Positions | FTE | Fully loaded |
|---|---:|---:|---:|
| **Standalone (headline)** | **403** | **392** | **$34.0M** |
| Pro-forma on Northstar | 394 | 383 | $32.9M |
| Shared-services synergy | −9 | −9 | −$1.2M |

The pro-forma line collapses the duplicated corporate layer back to the share Great Lakes already consumes and leaves the operating organisation untouched, since that is the business being bought. It is labour-only: systems, insurance and purchasing synergies are excluded.

Two external cross-checks land where they should. Labour is **34.9% of 2026E revenue** against the 35–40% benchmark, and **revenue per FTE is $249,000** against the $200–250K band. Both sit at the efficient edge rather than mid-range — consistent with 14.9% revenue growth outrunning hiring, and also what this would look like if headcount were modestly understated.

**Confidence differs by output.** Headcount is tighter: five signals from four independent source types converge inside a 60-person band, and the back-test puts the structural method at 2.5% error. Call it ±8%. Cost is wider, inheriting all of that and adding pay-structure error, since the comp's pay is Michigan pay re-indexed and Cardinal's benefit design is unobserved. Call it ±15%, roughly $29M to $39M.

## 2. Field Service end to end

Field Service means installation and repair technicians plus their direct supervisors. Branch managers sit above that line and are modelled in Executive & Corporate. Each step names its source and what only that source contributes.

**Total positions — triangulation.** 403 company-wide, of which the comp's field share (63.9%, after the standalone G&A layer is added) gives **257 field positions**.

**Split across families — Great Lakes, from Part 1.** Install 101.4, Service 134.9, Leadership 21.0. The alternative data cannot do this job; its field coverage is 0.28x–0.45x.

**Level ladder — Bayside and Pinnacle, from Part 1.** Great Lakes records every role level as `Unspecified`, so the ladder is borrowed: Bayside for HVAC (Service Tech I/II/III at 22/59/19, Installer I/II/Lead at 23/61/16) and Pinnacle for plumbing (Apprentice/Journeyman/Master at 19/61/21).

**Trade split — Great Lakes actuals blended with the Cardinal title mix.** Great Lakes runs 68% HVAC in service, Cardinal's live titles 87%; the model uses 75%. Install is all HVAC because neither source shows a plumbing install crew — a finding to confirm, not a certainty.

**Pay — Great Lakes medians, re-indexed on BLS.** The comp's median base by role is the anchor; the borrowed ladders contribute only the *ratio* of each level to that median, because level premia travel across geographies far better than absolute pay does. BLS OEWS May 2025 for SOC 49-9021, weighted on Cardinal's own branch footprint, gives **$61,595 against Michigan's $60,850 — an index of 1.012** (Cincinnati $62,240, Columbus $64,440, Dayton $62,500, Lexington $60,280, Louisville $58,930). Geography is second-order here, and now it is cited rather than asserted.

**Load factors — the Part 1 P&L.** Applied exactly as Part 1 applies them: overtime, commissions, bonus and taxes as a percentage of base, benefits per head rather than as a rate. The resulting factors run 1.38x to 1.51x.

| Role | Level | Positions | Annual base | Fully loaded | Total |
|---|---|---:|---:|---:|---:|
| HVAC Installer | I | 23.0 | $41,550 | $61,604 | $1.42M |
| HVAC Installer | II | 62.2 | $55,435 | $79,613 | $4.95M |
| HVAC Installer | Lead | 16.1 | $89,575 | $123,892 | $2.00M |
| HVAC Service Technician | I | 22.3 | $42,215 | $63,716 | $1.42M |
| HVAC Service Technician | II | 60.0 | $60,600 | $87,866 | $5.27M |
| HVAC Service Technician | III | 18.8 | $79,805 | $113,094 | $2.13M |
| Plumbing Service Technician | Apprentice | 6.7 | $43,074 | $64,844 | $0.43M |
| Plumbing Service Technician | Journeyman | 19.6 | $62,840 | $90,808 | $1.78M |
| Plumbing Service Technician | Master | 7.4 | $86,806 | $122,290 | $0.91M |
| Field Supervisor | — | 7.7 | $78,955 | $111,977 | $0.86M |
| Install Manager | — | 6.7 | $85,028 | $119,955 | $0.80M |
| Service Manager | — | 6.7 | $94,138 | $131,922 | $0.88M |
| **Total** | | **257** | | | **$22.9M** |

Three checks, one genuinely independent. **Fleet:** 260 vehicles against 257 field positions is 1.01 per position, matching how Great Lakes runs its own fleet. **Supervisor span:** 11.2:1, identical to the comp — true by construction, so it confirms arithmetic rather than reality. **Field leaders:** the model says 21, the live extract independently shows 18, a 17% gap. That one *is* independent, and it works precisely because supervisors are the one field population the alternative data covers well, at 0.86x.

**The provider's own salary estimate is usable only in aggregate.** Across field profiles carrying an estimate it averages $62,289 against this model's $61,799, within 0.8%. At role grain it is inverted: Apprentice HVAC Technician $59,500 above Senior Service Technician $55,000, HVAC Installer $54,500 above Lead Installer $50,000, Help Desk above IT Manager. A model built on provider salaries by role would have passed every total-level sanity check while pricing the ladder upside down.

## 3. Testing the model, and reviewing someone else's

### The back-test, executed

The estimate rests on one claim: given a total headcount, a contractor's field organisation can be predicted from a comparable contractor's structure. That is testable on data in hand. `src/backtest_structure.py` holds out each Northstar operating company in turn and predicts its field headcount from the mean field share of the other three, given nothing but its total.

| Held out | Given | Predicted | Actual | Error |
|---|---:|---:|---:|---:|
| Bayside Mechanical | 482 | 332.3 | 328 | +1.3% |
| Great Lakes Comfort Systems | 392 | 269.5 | 269 | +0.2% |
| Pinnacle Plumbing & Drain | 426 | 295.4 | 285 | +3.6% |
| Redwood Electric | 286 | 194.1 | 204 | −4.9% |

**Mean absolute error 2.5%, worst case 4.9%.** Splitting that total between families is harder, and the memo should not pretend otherwise: Service 3.8%, Install 7.3%, Leadership 9.5%. So the 257 total is the trustworthy number and the 101/135/21 split is the soft one — the opposite of how these models are usually read.

**The back-test also caught a live error.** The first run left Northstar Corporate in the comparison set. Every field estimate came out roughly 25% low with the same sign: 24.9% mean absolute error against 2.5%, and a −24.9% signed bias. A one-line comp-set error was worth ten times every pay assumption in the model combined.

### What actually moves the answer

| Assumption | Range tested | Swing in Field Service cost |
|---|---|---:|
| Total headcount | ±10% | 20.0% |
| Field share of headcount | ±5% | 10.0% |
| Load factor | ±5% | 10.0% |
| Geographic wage index | ±5% | 9.1% |
| HVAC / plumbing split | ±15% | 0.7% |

Headcount dominates, which is why most of the effort went there. The trade split barely registers, because HVAC and plumbing technicians are paid within a few percent of each other at Great Lakes — worth knowing before anyone spends a diligence day on it.

### Falsifiers, committed before the data room opens

Stating these now is the point; stating them afterwards is rationalisation. **The model is wrong if:** total headcount lands outside 370–440; field staff are below 60% or above 68% of the company; the plumbing share of service technicians is below 15% or above 40%; sales exceeds 10% of headcount, which the extract hints at and the comp does not; or Louisville is excluded from the 400. Any of these means the comp choice, not the arithmetic, has to change.

### Reviewing a teammate's model built this way

In this order, because it is the order in which the errors actually occurred:

1. **Entity resolution.** Which provider entities were kept, on what evidence beyond name similarity, and how many profiles were dropped? Here it was 22% of the file.
2. **Comp-set construction.** What is in the comparison set that should not be? Shared services in a field comp biased every estimate 25% low, silently.
3. **Coverage, not counts.** Was the alternative data tested for even role representation? If the model uses the profile *mix* as a structure anywhere, it is wrong.
4. **Staleness.** What is the cutoff, who chose it, and what does the answer look like at 12 and 36 months?
5. **External reconciliation.** Does the result survive revenue per employee, labour as a share of revenue, and a physical count like vehicles? Three checks that could fail independently beat one that passes.
6. **A measured error, not a confidence adjective.** Without a back-test the reliability claim is an opinion, and the data to run one is usually already in the model.
7. **Falsifiers in writing before diligence.** If the model cannot be wrong, it cannot be tested.

## Limitations and AI use

Cardinal is priced on Northstar's load factors because nothing else is observable; its real benefit design could move cost 5% either way and is the first diligence request. The comp is a single company, so Great Lakes' idiosyncrasies are inherited wholesale — the honest hedge is that the back-test measures exactly that risk at 2.5%. Level ladders are borrowed from two opcos in two other states. And the sales anomaly is unresolved: at 3.5x coverage, either the extract over-retains sales profiles or Cardinal runs a genuinely sales-heavy in-home model, and the org chart settles it in an afternoon.

Cursor with Claude profiled the extract, drafted the pipeline and this memo. The material judgements were made against output, not code: the Florida entity was found by reading a location crosstab rather than trusting the provider's match; the two-live-base split came from noticing that excluding unresolvable titles was quietly shrinking a headcount signal; and the Corporate contamination was caught because a −25% error appearing four times with the same sign is a structural bug, not noise. Fifteen assertions in `build_cardinal.py` exist so the next such error fails loudly.
