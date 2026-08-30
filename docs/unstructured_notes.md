**initial design**

This is the design document for a general assignment solver.  the goal is to take a set of proejcts which each have a planned monthly spend target, and then take a pool of people and assign them to the projects.  Most of the people will be pre-assigned in whole or part to programs manually by project planners, but it is a difficult problema dn takes a prohibitive amount of time to refine the work assignments plan down to the singleton hour.  In many cases trades have to be made. so this capability gives the project planners the ability to specify target information about the programs, and for each person, a hard minimum pre-assignment, a soft minimum, a soft maximum, and a hard maximum.  The solver works with these constraints to find an optimal assignment of people to projects for some number of hours.

Additionally to giving work assignments of people to project, there will be a month end retrospecitive merge of actuals data that will show waht number of hours each person billed to the project, and the total cost of those hours, and deltas will be computed. this will indicate to managers if someone is over or under their target, and the manager can find out why.

The user supplies the following combination of information:


## Task view

The task view shows each project at the root, an enumeration of people assigned to the project, totals for that project, and budget for that rpoject

Project 1
    Person 1
        Hard min
        Soft min
        Soft max
        Hard max
        Assigned hours
        Assigned cost
        Actual hours
        Actual cost
        Delta hours (Assigned - Actual)
        Delta cost (Assigned - Actual)

    Person 2
        ...
    
    ...

    Person L
        ...

     Totals (project)
        Total assigned hours
        Total assigned cost
        Actual hours
        Actual cost
        Delta total hours (Assigned - Actual)
        Delta total cost (Assigned -Actual)

     Budget
          Monthly Labor Spend Target (as a function of months)
          Travel Budget (single value_)
          ODC Budget (signle value)
          PoP Start Date
          PoP End Date
          Rate Structure (Project, OH, Fee)

Project 2
    ...

Project N
    ...


A hard min or max is a number of FTE (full time equivlent percentage) that is not to be surpassed.

A soft min or max is a number of FTE (full time eequilvlent percentage time) that the solver can surpass with a penalty.  I expect the project planners to input in some cases all four values (hard min, soft min, soft max, hard max), but in other cases they may just input hard mins or max, or just soft mins or max, or some other combination of these values for a worker pre-assigned to particular project.

Assigned Hours is solved for by the solver implemented using google ortools
Assigned cost is the computed cost using that worker's salary information and the corporate rate structure reference data.

Actual hours are populated via another process that is TBD created. these values come from each worker's time cards and another TBD automated process will  populate them.

Actual cost will be computed from Actual hours, the same way that Assigned hours is computed

Delta hours and delta cost will be computed once actual hours are populated and acutal cost is computed. this is a reporting product that will be used to provide observability for managers into worker activities and seek information if assigned doesn't match actual.
     


## Resource View

Person 1
    Project 1
        Hard min
        Soft min
        Soft max
        Hard max
        Assigned hours
        Assigned cost
        Actual hours
        Actual cost

    Totals (person)
        Total assigned hours
        Total assigned cost
        Actual hours
        Actual cost

    Salary
        Year Salary (timeline, because salary ajustments happen periodically)
        Monthly Project Rate (timeline, because salary adjustments and rate adjustments happen periodically)
        Monthly OH Rate (timeline, OH rate is different than Project rate)
        Monthly Fee Rate (timeline, Fee rate is differenet than project rate)

    Limits
        Hard Max number of projects
        Soft Max number of projects

Person 2
    ...

...

Person M

The resource view is mostly a pivot of the project view, containing much of the same information, but the root of the tree of information is the human resource (worker). the planner using this software should be able to make adjustments to the hard min, soft min, hard max, and soft max in either the project view or the resource view.  the resource view also incldues worker limits in terms of the hard max number of projects they can be assigned to (varies by person and their desires/abililties) as well as a soft max number of projects.  This ensures that workers are not assigned to many projects for a small number of % fte each month.

## Reference Data

Number of workable hours each month
    The workable hours in each month is neccessary to determine the worker's exact rate that month. the rate equation is salary/12/workable_hours_current_month = worker_hourly_rate. then worker_hourly_rate * wrap_rate is the worker's cost per hour that month.  Most workers charge projects which use the project wrap rate. but some may charge projects that utilize the overhead (OH) or Fee wrap rates in special circumstances.
Project Wrap Rate (each month)
OH Wrap Rate (each month)
Fee Wrap Rate (each month)

the wrap rates are updated once per year so the system needs to be aware of this. currently i have this documented as a wrap rate per month but in reality the wrap wrate for the coprporate fisical year (call it UFY) which starts on July 1 of each year is the important boundary where wrap rates will be subject to change


## Other concerns

As much as possible, the solver should avoid "churn" meaining that work assignments should be as consistent as possible from month to month without sudden reductions to zero for any person on a project, or without people being phased in and out of a project multiple times.  Steady pulse for performance is a management goal.  Additionally, unless otherwise specififed, the default hard soft max number of projects should be 2 projects, and the hard max should be 4 for all workers.  These can be changed by the planners but the defaults should be these.  It should be rare that the solver violates the soft max number of projects.

The ultimate goal for the project is to spend out by the end of the PoP.  A typical goal is a linear spend (same spend per month) from pop start to pop end, but this is rarely what transpires.  I would like the solver to be able to use non-linear spend plans in favor of personnel churn or exceeding personnel soft max number of projects.  Some projects can be extended, this is called a no cost extension (NCE) and it would be good if the solver could reccomend NCE if solutions that respect teh worker constraints can't be met.

Wherever possible, we do not want to start a project in the first month with a full complement of workers.  Ideally the first month includes a smaller set of workers representing the project PIs and Co-PIs and key technical contributors. this is so the team can determine a project plan in advance of the full team showing up for tasking. this will likely be manually enforced by the hard/soft min/max assignments tha are pre-assigned before the solver is run.

I would like the interface to this solver to be some kind of linked spreadsheet or excel workbook, but ideally not excel itself.  the solver shall be fully implemented using open source python packages (or python bindings around other packages)



**implentation notes**

Unless thedre is a good reason not to or a better alternative, i'd like the optimization to be done using google ORTools.

I want packages for this work to be installed in a conda virtual environment called general_assignment_solver.

I want a medium-sized example to be created based on the instructions I left here: examples/medium_example/unstructured_notes_medium_example.md. I want all of the data files required to run the medium example to be stored in that folder, a python script that is run that reads the example data and runs the example, and an example readme that fully explains how to run the example and a tutorial on how to use the software written for a planner who would be using the tool.

I want a minimally specified environment.yml file and instructions on how to use conda to replicate the environment from scratch using this file, and to run the medium_example.


**next directive**

please include mermaid system architecture and process flow diagrams throughout my documentation where relevant to communicating the design and intended use case.

once the software implementation is complete and outputs can be generated from the medium_example, I would like a slide presentation built in marp explaining the work assignment scenario in medium_example, what this software/solver does, and the process flow diagram showing how to use this tool in a project planning proces over multiple months, and example outputs.