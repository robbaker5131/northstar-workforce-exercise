# Northstar Home Services Group — Data Dictionary

## northstar_census.csv
HRIS export consolidated from the operating companies' systems. As-of date: 2026-08-31.

| Column | Definition |
|---|---|
| employee_id | Employee identifier assigned by the operating company's HRIS. Prefix indicates source system. |
| opco | Operating company, or "Northstar Corporate" for shared-services staff. |
| department | Department as recorded in the source HRIS. |
| job_title | Job title as recorded in the source HRIS. |
| job_level | Internal level code, where the source HRIS carries one. |
| employee_type | Employment classification as recorded in the source HRIS. |
| pay_rate | Pay rate as recorded in the source HRIS. |
| pay_basis | Basis of pay_rate (Annual or Hourly), where the source HRIS carries it. |
| scheduled_weekly_hours | Scheduled hours per week, where the source HRIS carries it. |
| hire_date | Most recent hire date. |
| termination_date | Termination date, where recorded. |
| status | Employment status as recorded in the source HRIS. |
| work_state | Primary work location state. |

## northstar_pnl_labor.csv
Labor cost by department from the finance system, trailing twelve months ended 2026-06-30. All amounts USD.

| Column | Definition |
|---|---|
| pnl_department | Finance department. |
| base_wages_salaries | Regular wages and salaries paid. |
| overtime | Overtime premium and hours paid. |
| commissions_spiffs | Sales commissions and technician performance incentives. |
| bonus | Discretionary and plan bonuses. |
| payroll_taxes | Employer payroll taxes. |
| benefits | Employer cost of health, retirement, and other benefits. |
| contract_labor | Payments to contract and temporary labor. |
| total_labor_cost | Sum of the above. |
| avg_headcount_ttm | Average monthly headcount over the period per the finance system. |

## Notes
- The workforce model built from these files is consumed at the standardized role level, not the raw job title level.
- The model prices positions at fully loaded cost.
