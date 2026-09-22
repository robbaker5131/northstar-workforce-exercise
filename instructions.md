Atomic — Analytics Manager Technical Exercise
About this exercise
You’ll work with data for a fictional private-equity-owned company, Northstar Home Services Group, a residential HVAC, plumbing, and electrical platform with approximately 1,800 employees across four acquired operating companies and a corporate shared-services group. Northstar has signed a letter of intent to acquire a smaller company, Cardinal Comfort Services.
The exercise has two parts:
•	Part 1 — Census Onboarding (code required). Northstar has shared an employee census export and a department-level P&L. Build a clean, position-level workforce model at fully loaded cost, reconciled to the P&L. This is the baseline every downstream analysis will be priced against, so it has to be defensible to Northstar’s CFO.
•	Part 2 — Outside-In Workforce Simulation (written methodology). There is no data room for Cardinal yet. Using public signals, an alternative-data extract of current employee profiles, and your Northstar model, design the methodology you would use to estimate Cardinal’s workforce and labor cost, and design how you would test whether the result can be trusted.
Time
This is designed to take approximately 4 hours. Suggested pacing: Part 1 ~2 hours, Part 2 ~2 hours. We would rather see clear reasoning on fewer items than rushed completeness.
Files provided
File	Description
northstar_census.csv	Employee census export, as of 2026-08-31
northstar_pnl_labor.csv	Labor cost by department, trailing twelve months ended 2026-06-30
data_dictionary.md	Column definitions for the two files above
cardinal_brief.md	Public signals compiled on Cardinal Comfort Services
cardinal_entity_mapping.csv	Alternative-data provider entities matched to Cardinal
cardinal_profiles.csv	Current employee profiles held by the provider against those entities
Deliverables
Part 1: your code; the clean workforce model (one row per active position with standardized role, department, FTE, annual base, fully loaded annual cost, fully loaded hourly cost); a reconciliation to the P&L by department; and a methodology and assumptions memo of no more than two pages, written for the engagement delivery team who will build on your model.
Part 2: a methodology memo of roughly 3–5 pages with three required sections.
1.	Estimate Cardinal’s company-wide FTE and fully loaded annual labor cost to ground the model. State what you relied on, how you weighted each input, and how confident you are.
2.	Simulate Cardinal’s Field Service department (installation and repair technicians and their direct supervisors) end to end, producing the same position-level structure as Part 1. Be explicit about which data sources you use at each step and what each contributes.
3.	Describe how you would test whether the resulting model can be trusted, and how you would review a model that someone on your team produced with this method.
A full role-by-role model for the whole company is not required.
What we’re evaluating
Your reasoning, your assumptions, and whether a skeptical reader could trust and reproduce your work. Clean code matters less than a clear account of what you did and why. We expect you to use AI tools; please tell us briefly how you used them.
Format
Deliver however makes sense to you: a notebook plus a document, a repository, a set of files. Submit code alongside written analysis.
What happens next
We’ll review your submission together in a 60-minute conversation. There is no presentation. We will walk through your work, probe your reasoning, and extend the problem on the spot.
