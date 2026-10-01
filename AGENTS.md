# AGENTS.md — general assignment solver

A MILP-driven labor allocation and spend-planning tool: given people, concurrent
projects with monthly spend targets, and per-person-per-project hour bounds, it
solves for an assignment that hits the targets, respects capacity and
fragmentation limits, and stays stable across plan revisions.

## Start here

| Read | For |
|---|---|
| `README.md` | Getting it running |
| `docs/README.md` | Design rationale — start here for why, not how |
| `docs/08-grist-ui-design.md` | The planner loop: import a ballpark, tweak and lock, solve, restore an iteration |
| `docs/09-planner-tutorial.md`, `docs/10-medium-example-tutorial.md` | Manual test protocols — small example, then three months on the medium one |
| `tests/` | Behavior worth preserving |
| `slides/` | A 15-slide Marp deck for program managers; see `slides/README.md` |

Setup is conda: `conda env create -f environment.yml` then
`conda activate general_assignment_solver`.

## Things worth knowing

- **Stability between revisions is a requirement, not a nicety.** A solver that
  returns a different but equally optimal assignment each run is useless to the
  people being assigned. Check what the existing objective does about this
  before changing it.
- **An infeasible model needs to say why.** "No solution" is not an answer a
  planner can act on; prefer diagnostics that name the binding constraint.
- **The working assignment is one object in three roles.** `Allocation`'s open
  months are simultaneously the imported ballpark, the hand-tweaked plan, the
  solver's starting point and the solver's output
  (`allocsolver/io/working_assignment.py`). That identity is what makes "this
  solve's result is the next solve's input" true without a conversion step —
  don't split it back into separate input and output tables.
- **`solve(plan, baseline=...)` is the "follow my ballpark" knob, and its
  weight matters more than its wiring.** The churn term measures distance from
  the baseline. At the default weight of 5 — calibrated for stability between
  two *solver outputs* — it mostly only breaks ties and will not reshape a plan
  toward a hand-built assignment. `config.ADHERENCE_CHURN_WEIGHTS` holds the
  measured levels; `docs/08-grist-ui-design.md` has the numbers. Past `close`,
  adherence is bought with the spend targets.
- **Three manual inputs, three different jobs.** A ballpark cell is a starting
  number the solver may move; a `Pre_Assignments` row is an hour *range* it must
  respect; a `locked` cell is a number it cannot move at all. All three are
  supported and they are not interchangeable.
- **Locks need their own diagnostics, and C1/C2 don't apply to them.**
  `constraints.py` skips the hard/soft bound constraints for fixed cells, so a
  lock above its cell's `hard_max` is legal by design, not a conflict. What can
  genuinely break is capacity (C3), the concurrency ceiling (C6) and hard spend
  targets (C4) — and the elastic relaxation cannot report any of it, because it
  re-pins locked cells verbatim and so goes infeasible itself, returning an
  empty slack report. `allocsolver/solve/locks.py` computes those conflicts
  directly in Python instead. Don't "fix" that by relaxing locks in the elastic
  model: slack on a locked cell reports that a deliberate pin had to move, which
  is useless.
- **Nothing reads the plan by re-solving it.** Reports, exports and variance all
  read the working assignment (`_working_hours` in `planner_api/main.py`).
  Re-solving to "look up" the current hours can legitimately return a different
  equally optimal plan, which is how a budget report ends up disagreeing with
  the `Allocation` table for no visible reason.
- **Importing a ballpark replaces every open month, wholesale.** A cell the
  file omits ends up empty — correct when the ballpark *is* the plan, and a
  loaded gun against a mid-horizon plan: on the medium example a one-row import
  collapses ~4,700 cells to one. Recovery is restoring the last `solve`
  iteration. The safe round trip is Download-current-as-CSV, edit that, re-import.
  A merge/upsert import mode is the obvious missing option and hasn't been built.
- **`examples/medium_example/data/` is checked in fully closed.** Its
  `meta.json` says `closed_through: 2031-12` because those files are the output
  of `simulate_full_horizon.py`. Seeding a Grist doc from them yields a planner
  with nothing to plan. Run `python generate_data.py --seed 42` first, which
  resets it to `2027-02`.
- **`grist_planner/` deps aren't in the conda env.** `fastapi` and `httpx` live
  only in the container image, so the FastAPI handlers can't be imported by the
  test suite. `planner_api/history.py` avoids importing `httpx` (its
  `TableStore` protocol exists for exactly this) and so *is* tested. To verify
  the handlers, stand up a throwaway stack on alternate ports rather than
  touching a running instance:
  `docker compose -p planner_verify --env-file <alt.env> up -d`, provision with
  `--seed-dir /examples/small_example/data`, drive it with `curl`, then
  `down -v`.

## How I work — standing preferences

These are the same in every repository of mine. They are restated in each one
so that any assistant reads them, not only the one configured on my machine.

**Git is mine.** Never run `git commit` or `git push`, in any repository, for
any reason. Reading history is encouraged — `log`, `diff`, `status`, `show` —
and so is telling me when a good commit point has been reached, or drafting a
commit message for me to use. Finish the work, leave it uncommitted, and say
what changed and where.

**Hardware is mine.** Do not build SD-card images, `rsync` to a device, open an
`ssh` session to one, or run anything on a Raspberry Pi or the cyberdeck unless
I ask in that message. Hand me the exact commands to copy and paste — one block
per step, in order — say what each should print, and stop. I will run them and
paste the output back. Local work in the repository needs no such restraint.

**Writing.** No British spellings; US throughout. Design documents are
declarative: no hero's-journey narrative, no second-person "you", and never
state something as fact and then refute it a few lines later. For an article
already published, add a dated update section rather than rewriting the
narrative — the wrong turns are part of why it is worth reading. Do not repeat
a warning I have already acknowledged.

**Images.** Look at any photograph or screenshot before adding it to an
article, a slide deck, or a repository. Phone numbers show up in radio screens
and log captures, coordinates show up in beacon lines and station pages, and
backgrounds show rooms. Say what you found and redact it rather than guess.

**Destructive commands.** `/dev/sdX` stays a placeholder in any flashing or
disk-writing instructions. Never substitute a real device node.

**Amateur radio.** Test traffic uses my own callsign and its SSIDs — never
another operator's call, unless I explicitly ask for one.

**Working style.** I start fresh sessions often rather than carrying one for
weeks, so assume no memory of previous conversations. Everything you need
should be in this file or in the documents it points at.

**Keeping this file true is part of the work.** Anything dated here records
what was true on that date, not what is true now — check it against the
repository before relying on it, and correct it when it is wrong. When a
session has changed how the project works, turned up a gotcha worth the next
session not rediscovering, or outdated something in a "where it stands"
section, propose the edit to this file before the session ends. Do not wait to
be asked, and do not save it for a tidy-up later: the next session starts cold,
and this file is most of what it gets.
