# Notes

Informal, chronological notes — preserved as the original record of intent, not
rewritten into a design doc. See `01-system-overview.md` onward for the actual
resolved design.

## Initial design

This is the design document for a general assignment solver. The goal is to
take a set of projects which each have a planned monthly spend target, and
then take a pool of people and assign them to the projects. Most of the people
will be pre-assigned in whole or part to programs manually by project
planners, but it is a difficult problem and takes a prohibitive amount of time
to refine the work assignments plan down to the singleton hour. In many cases
trades have to be made. So this capability gives the project planners the
ability to specify target information about the programs, and for each
person, a hard minimum pre-assignment, a soft minimum, a soft maximum, and a
hard maximum. The solver works with these constraints to find an optimal
assignment of people to projects for some number of hours.

Additionally to giving work assignments of people to project, there will be a
month-end retrospective merge of actuals data that will show what number of
hours each person billed to the project, and the total cost of those hours,
and deltas will be computed. This will indicate to managers if someone is over
or under their target, and the manager can find out why.

The user supplies the following combination of information:

### Task view

The task view shows each project at the root, an enumeration of people
assigned to the project, totals for that project, and budget for that project.

- **Project 1**
  - Person 1
    - Hard min
    - Soft min
    - Soft max
    - Hard max
    - Assigned hours
    - Assigned cost
    - Actual hours
    - Actual cost
    - Delta hours (Assigned − Actual)
    - Delta cost (Assigned − Actual)
  - Person 2
    - ...
  - ...
  - Person L
    - ...
  - **Totals (project)**
    - Total assigned hours
    - Total assigned cost
    - Actual hours
    - Actual cost
    - Delta total hours (Assigned − Actual)
    - Delta total cost (Assigned − Actual)
  - **Budget**
    - Monthly Labor Spend Target (as a function of months)
    - Travel Budget (single value)
    - ODC Budget (single value)
    - PoP Start Date
    - PoP End Date
    - Rate Structure (Project, OH, Fee)
- **Project 2**
  - ...
- **Project N**
  - ...

A hard min or max is a number of FTE (full time equivalent percentage) that is
not to be surpassed.

A soft min or max is a number of FTE (full time equivalent percentage time)
that the solver can surpass with a penalty. I expect the project planners to
input, in some cases, all four values (hard min, soft min, soft max, hard
max), but in other cases they may just input hard mins or max, or just soft
mins or max, or some other combination of these values for a worker
pre-assigned to a particular project.

Assigned Hours is solved for by the solver, implemented using Google OR-Tools.
Assigned cost is the computed cost using that worker's salary information and
the corporate rate structure reference data.

Actual hours are populated via another process that is TBD created. These
values come from each worker's time cards, and another TBD automated process
will populate them.

Actual cost will be computed from Actual hours, the same way that Assigned
hours is computed.

Delta hours and delta cost will be computed once actual hours are populated
and actual cost is computed. This is a reporting product that will be used to
provide observability for managers into worker activities and seek
information if assigned doesn't match actual.

### Resource View

- Person 1
  - Project 1
    - Hard min
    - Soft min
    - Soft max
    - Hard max
    - Assigned hours
    - Assigned cost
    - Actual hours
    - Actual cost
  - **Totals (person)**
    - Total assigned hours
    - Total assigned cost
    - Actual hours
    - Actual cost
  - **Salary**
    - Year Salary (timeline, because salary adjustments happen periodically)
    - Monthly Project Rate (timeline, because salary adjustments and rate
      adjustments happen periodically)
    - Monthly OH Rate (timeline, OH rate is different than Project rate)
    - Monthly Fee Rate (timeline, Fee rate is different than project rate)
  - **Limits**
    - Hard Max number of projects
    - Soft Max number of projects
- Person 2
  - ...
- ...
- Person M

The resource view is mostly a pivot of the project view, containing much of
the same information, but the root of the tree of information is the human
resource (worker). The planner using this software should be able to make
adjustments to the hard min, soft min, hard max, and soft max in either the
project view or the resource view. The resource view also includes worker
limits in terms of the hard max number of projects they can be assigned to
(varies by person and their desires/abilities) as well as a soft max number of
projects. This ensures that workers are not assigned to many projects for a
small number of % FTE each month.

### Reference Data

- **Number of workable hours each month** — The workable hours in each month
  is necessary to determine the worker's exact rate that month. The rate
  equation is `salary / 12 / workable_hours_current_month = worker_hourly_rate`.
  Then `worker_hourly_rate * wrap_rate` is the worker's cost per hour that
  month. Most workers charge projects which use the project wrap rate, but
  some may charge projects that utilize the overhead (OH) or Fee wrap rates in
  special circumstances.
- **Project Wrap Rate** (each month)
- **OH Wrap Rate** (each month)
- **Fee Wrap Rate** (each month)

The wrap rates are updated once per year, so the system needs to be aware of
this. Currently I have this documented as a wrap rate per month, but in
reality the wrap rate for the corporate fiscal year (call it UFY), which
starts on July 1 of each year, is the important boundary where wrap rates are
subject to change.

### Other concerns

As much as possible, the solver should avoid "churn," meaning that work
assignments should be as consistent as possible from month to month, without
sudden reductions to zero for any person on a project, or without people being
phased in and out of a project multiple times. Steady pulse for performance is
a management goal. Additionally, unless otherwise specified, the default soft
max number of projects should be 2, and the hard max should be 4 for all
workers. These can be changed by the planners, but the defaults should be
these. It should be rare that the solver violates the soft max number of
projects.

The ultimate goal for the project is to spend out by the end of the PoP. A
typical goal is a linear spend (same spend per month) from PoP start to PoP
end, but this is rarely what transpires. I would like the solver to be able to
use non-linear spend plans in favor of personnel churn or exceeding personnel
soft max number of projects. Some projects can be extended; this is called a
no-cost extension (NCE), and it would be good if the solver could recommend an
NCE if solutions that respect the worker constraints can't be met.

Wherever possible, we do not want to start a project in the first month with a
full complement of workers. Ideally the first month includes a smaller set of
workers representing the project PIs and Co-PIs and key technical
contributors — this is so the team can determine a project plan in advance of
the full team showing up for tasking. This will likely be manually enforced by
the hard/soft min/max assignments that are pre-assigned before the solver is
run.

I would like the interface to this solver to be some kind of linked
spreadsheet or Excel workbook, but ideally not Excel itself. The solver shall
be fully implemented using open source Python packages (or Python bindings
around other packages).

## Implementation notes

Unless there is a good reason not to or a better alternative, I'd like the
optimization to be done using Google OR-Tools.

I want packages for this work to be installed in a conda virtual environment
called `general_assignment_solver`.

I want a medium-sized example to be created based on the instructions I left
here: `examples/medium_example/unstructured_notes_medium_example.md`. I want
all of the data files required to run the medium example to be stored in that
folder, a Python script that is run that reads the example data and runs the
example, and an example README that fully explains how to run the example and
a tutorial on how to use the software, written for a planner who would be
using the tool.

I want a minimally specified `environment.yml` file and instructions on how to
use conda to replicate the environment from scratch using this file, and to
run the medium example.

## Next directive

Please include Mermaid system architecture and process flow diagrams
throughout my documentation where relevant to communicating the design and
intended use case.

Once the software implementation is complete and outputs can be generated from
the medium example, I would like a slide presentation built in Marp explaining
the work assignment scenario in the medium example, what this software/solver
does, and the process flow diagram showing how to use this tool in a project
planning process over multiple months, and example outputs.
