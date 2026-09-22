first asked Claude AI what fully loaded cost means
- it means total annual cost to the company for that employee, not just base salary
then asked does position level roles mean group together employees with the same title
- it means start at the individual and roll up to position title if necessary
created new repo for candidate-exercise to store all data in cursor
- added process files
    - explored files
- copied Word file into md file so that AI can read it
opened north_census in excel to understand data and created some pivot tables to understand the data
- 1811 employees, 1711 active (100 terminated)
- most from Field dept
- lots of blanks in data
- cardinal entity mapping noticed FL entity which doesn't belong
- noticed status column with terminated value
- noticed corporate roles from Northstar
- attempted to reconcile hourly employees to annualized salary but there were too many blanks
asked AI between AZ, FL, MI, and TX which state is most similar to OH and KY in terms of labor cost
- Michigan most similar
- will consider this for Cardinal estimated costs
asked cursor Please review @instructions.md let's start with deliverable part 1. can you help create a plan for this. Please review all data in this repo ---- in PLAN mode with Claude Opus 5 High
- accepted the recommended approaches to 2 questions with the plan
    - deliverable format?
        - python scripts + csv outputs + markdown memo
    - census point in time
        - bridge and explain, do not force-fit
- asked cursor to reduce the length of the methodology memo so that it's 2 pages (first output was 4 pages)
- asked Claude with methodology memo attached to read the memo
asked cursor let's do deliverable part 2  ---- in PLAN mode with Claude Opus 5 High
- accepted the recommended approaches to 2 questions with the plan
    - brief calls for written memo
        - memo plus reproducible code and outputs
    - cardinal's fully loaded costs depends
        - standalone headline, pro-forma noted
asked Claude what a pro-forma is
- most likely an assumption that the acquisition of Cardinal was successful and here's a representation of Northstar with Cardinal
- it could also be adjustments based on Cardinal
asked Claude with the cardinal memo attached to answer the 3 questions from the instructions
1.	Estimate Cardinal’s company-wide FTE and fully loaded annual labor cost to ground the model. State what you relied on, how you weighted each input, and how confident you are.
2.	Simulate Cardinal’s Field Service department (installation and repair technicians and their direct supervisors) end to end, producing the same position-level structure as Part 1. Be explicit about which data sources you use at each step and what each contributes.
3.	Describe how you would test whether the resulting model can be trusted, and how you would review a model that someone on your team produced with this method.



