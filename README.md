# Analytics Manager Technical Exercise — Northstar Home Services Group

Two deliverables: a position-level workforce model for Northstar built from a raw census
and a department P&L, and an outside-in estimate of Cardinal Comfort Services built
without a data room. Both are reproducible pipelines, not spreadsheets.

## Read these two documents

| Document | Covers | Length |
|---|---|---|
| [`docs/methodology_memo.pdf`](docs/methodology_memo.pdf) | Part 1 — census onboarding, cleaning decisions, load factors, P&L reconciliation | 2 pages |
| [`docs/cardinal_methodology_memo.pdf`](docs/cardinal_methodology_memo.pdf) | Part 2 — company-wide estimate, Field Service simulation, back-test and review checklist | 5 pages |

Both are also committed as `.docx` and as the `.md` source they were generated from.

## Headline results

**Part 1 — Northstar.** 1,665 filled positions, 1,646.0 FTE, $97.22M annual base,
**$138.74M fully loaded** at a 1.427x blended load, plus 40 contract workers annualised
at $3.70M. Reconciles to the P&L at +1.3% on total employee cost, with each department
decomposed into a volume effect and a rate/mix effect rather than a plug.

**Part 2 — Cardinal.** **403 employees, 392 FTE, $34.0M fully loaded** standalone;
$32.9M pro-forma once Northstar absorbs the duplicated G&A layer. Field Service is
**257 positions at $22.9M**, built at position and level grain on the Part 1 column
contract. The structural method is back-tested at **2.5% mean absolute error**.

The single largest finding is an entity-resolution one: 22% of the alternative-data
extract is a different company, a Florida HVAC parts wholesaler that the provider
matched to Cardinal on name similarity.

## Reproduce

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python src/build_model.py         # Part 1  -> output/, 12 validation checks
python src/build_cardinal.py      # Part 2  -> output/, 15 validation checks
python src/backtest_structure.py  # leave-one-out back-test of the Part 2 method
```

Each script prints a full summary and a list of validation checks, and exits non-zero if
any check fails. Run them in that order — Part 2 reads the Part 1 model as its comparable.

Regenerating the memos additionally needs Microsoft Word, which is used only to export
PDFs at a verified page count:

```bash
python src/memo_to_docx.py                               # Part 1 memo
python src/memo_to_docx.py docs/cardinal_methodology_memo.md
```

## What is where

```
candidate-exercise/   Source data as provided. Not modified.
config/               Every mapping and tunable input, as editable CSV rather than code.
src/                  The pipelines.
output/               Generated. Committed so results can be read without running anything.
docs/                 The two memos.
process.md            Working notes kept while solving it, including where AI was used.
```

**`config/` is the file a reviewer should open first.** Crosswalks, load-factor sources,
staleness cutoffs, signal weights and the geographic wage index all live there, so an
assumption can be flexed without reading a line of Python.

| Config file | Holds |
|---|---|
| `department_map.csv`, `role_map.csv` | Raw department and title to standardized department, role and level |
| `cardinal_assumptions.csv` | Every Part 2 judgement input, each with a source and a rationale |
| `cardinal_title_map.csv` | The 62 alternative-data provider titles onto the Part 1 taxonomy |
| `bls_wage_index.csv` | BLS OEWS metro medians behind the geographic pay index |

### Key outputs

| File | What it is |
|---|---|
| `output/workforce_model.csv` | Part 1 deliverable: one row per filled position at fully loaded cost |
| `output/reconciliation_by_department.csv` | The P&L bridge, volume and rate/mix by department |
| `output/exceptions.csv` | Every imputation and override, with the rule that produced it |
| `output/cardinal_field_service_model.csv` | Part 2 deliverable: Cardinal Field Service at position and level grain |
| `output/cardinal_profile_base.csv` | All 645 provider profiles with an `excluded_reason` on each |
| `output/backtest_leave_one_out.csv` | Measured error of the Part 2 method, plus the contaminated comp-set scenario |

## Notes

Data is fictional and was supplied with the exercise. AI use is disclosed in the closing
section of both memos and in `process.md`.
