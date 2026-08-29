# 04. Solver Design

## Sets

| Symbol | Meaning |
|---|---|
| `P` | Projects with status `active`, indexed `p` |
| `W` | People, indexed `w` |
| `M` | Months in the solve horizon, ordered, indexed `m` |
| `E` | Eligible cells, the subset of `P x W x M` where the pair is eligible, `m` is within `[pop_start[p], pop_end[p]]`, and `m` is within `[active_from[w], active_to[w]]` |
| `F` | Fixed cells, the subset of `E` that is locked or in a closed month |

Variables are generated over `E`, not over the full cross product. At the design ceiling this is the difference between a tractable model and an intractable one.

## Parameters

| Symbol | Source | Meaning |
|---|---|---|
| `R[p,w,m]` | composed from `rates` | Loaded hourly cost |
| `cap[w,m]` | `capacity` | Available hours |
| `hmin, smin, smax, hmax [p,w,m]` | `bounds` | Hour bounds |
| `T[p,m]` | `targets` | Monthly labor spend target |
| `tol[p,m]` | `targets` | Unpenalized deviation band |
| `base[p,w,m]` | last accepted baseline | Prior assigned hours |
| `fix[p,w,m]` | `allocation` | Value for cells in `F` |
| `maxproj[w]` | `people` | Concurrent project limit |

## Decision variables

| Variable | Domain | Meaning |
|---|---|---|
| `x[p,w,m]` | continuous, `>= 0` | Hours assigned |
| `y[p,w,m]` | binary | 1 if the person is staffed on the project that month |
| `u[p,w,m]` | continuous, `>= 0` | Shortfall below soft min |
| `o[p,w,m]` | continuous, `>= 0` | Excess above soft max |
| `dp[p,m], dm[p,m]` | continuous, `>= 0` | Spend over and under target |
| `idle[w,m]` | continuous, `>= 0` | Unassigned capacity |
| `cp[p,w,m], cm[p,w,m]` | continuous, `>= 0` | Churn up and down vs baseline |

`y` is why this is a MILP rather than an LP. Without it, `hard_min` would force every eligible person onto every project at their minimum, which is nonsense. `y` makes `x` semi-continuous: either zero, or at least `hard_min`.

## Constraints

**C1. Semi-continuous assignment.** For all `(p,w,m)` in `E`:

```
hmin[p,w,m] * y[p,w,m]  <=  x[p,w,m]  <=  hmax[p,w,m] * y[p,w,m]
```

Both bounds gated by `y`. The upper gate is what forces `x = 0` when `y = 0`.

**C2. Soft bounds with elastic slack.** For all `(p,w,m)` in `E`:

```
x[p,w,m] + u[p,w,m]  >=  smin[p,w,m] * y[p,w,m]
x[p,w,m] - o[p,w,m]  <=  smax[p,w,m] * y[p,w,m]
```

Gating by `y` prevents charging a soft-min penalty for a person who is simply not on the project. Without the gate, the objective pays to staff people it should leave off.

**C3. Capacity.** For all `w`, `m`:

```
sum over p of x[p,w,m]  +  idle[w,m]  =  cap[w,m]
```

Written as an equality with an explicit `idle` term rather than as an inequality. Uncovered capacity is a real cost (it lands in overhead or B&P), so the model should see it and be able to trade against it. If uncovered capacity is genuinely free, set its weight to zero; do not change the constraint.

**C4. Spend target.** For all `p`, `m`:

```
sum over w of R[p,w,m] * x[p,w,m]  -  T[p,m]  =  dp[p,m] - dm[p,m]
```

For `target_type = hard`, additionally:

```
sum over w of R[p,w,m] * x[p,w,m]  <=  T[p,m]
```

which makes the target a ceiling rather than an aim point. A funding cap and a burn target are different objects and this is where the difference lives.

Tolerance is handled by penalizing only the portion outside the band, via `dp' >= dp - tol[p,m]` with `dp' >= 0` and penalizing `dp'`.

**C5. Fixed cells.** For all `(p,w,m)` in `F`:

```
x[p,w,m] = fix[p,w,m]
```

Applied as variable bound fixing rather than as a constraint row, which lets presolve remove them entirely.

**C6. Fragmentation.** For all `w`, `m` where `maxproj[w]` is set:

```
sum over p of y[p,w,m]  <=  maxproj[w]
```

**C7. Churn linearization.** For all `(p,w,m)` in `E \ F`:

```
x[p,w,m] - base[p,w,m]  =  cp[p,w,m] - cm[p,w,m]
```

`cp + cm` is then the absolute deviation from baseline, valid as a linearization because the objective minimizes both terms.

## Objective

```
minimize
    W_target    * sum over p,m   ( dp'[p,m] + dm'[p,m] )      / norm_dollars
  + W_soft      * sum over E     ( u[p,w,m] + o[p,w,m] )      / norm_hours
  + W_idle      * sum over w,m   ( idle[w,m] )                / norm_hours
  + W_churn     * sum over E\F   ( cp[p,w,m] + cm[p,w,m] )    / norm_hours
  + W_headcount * sum over E     ( y[p,w,m] )                 / norm_count
```

**Normalization is not optional.** Spend deviation is in dollars, soft violations are in hours, headcount is a count. Without dividing each term by a scale factor, the weights are uninterpretable and tuning becomes trial and error. Use the horizon totals as the norms: total target dollars, total capacity hours, total eligible cells.

**Suggested starting weights:** target 100, soft 10, churn 5, idle 3, headcount 1. Target dominance is deliberate. The stated purpose of the tool is hitting the spend target; everything else is a tiebreaker among plans that hit it.

**The churn term is the one people leave out and regret.** Without it, a one-line change to a bound produces a completely reshuffled plan, because the solver is indifferent among equally optimal solutions and will return whichever one branch-and-bound reached first. Operators lose trust in a tool that scrambles the plan for no visible reason, and they stop re-solving, and then the tool is dead. Five percent weight on stability buys the plan's credibility.

### Lexicographic alternative

If weight tuning proves unstable, solve in stages instead:

```
1. Minimize target deviation.        -> D*
2. Constrain deviation <= D* * 1.02, minimize soft violations.  -> S*
3. Constrain both, minimize churn.
```

Slower (three solves) but produces defensible answers: "we hit the target, then among target-hitting plans we minimized bound violations." That sentence is easier to defend in a program review than a weight vector.

## Infeasibility diagnostics

A bare `infeasible` is useless to a program manager. The system never surfaces one.

**Elastic re-solve.** On infeasibility, rebuild with a slack variable on every hard constraint, penalized at a weight far above any other objective term:

```
C1':  x >= hmin * y - s_hmin
C1':  x <= hmax * y + s_hmax
C3':  sum_p x  <=  cap + s_cap
C4':  hard targets get s_target
```

This model is always feasible. The nonzero slacks are exactly the constraints that had to break, and their magnitudes are the required relaxation. The report reads:

```
INFEASIBLE. Minimum relaxation to reach feasibility:

  capacity   J. Doe        2026-11    +38.0 h   over available 160.0
  capacity   J. Doe        2026-12    +12.5 h
  hard_min   PROJ-C / R. Smith 2027-02  -8.0 h  (hard_min 40, achievable 32)

  Driver: PROJ-A and PROJ-C both require J. Doe at hard_min in Nov,
          totaling 198 h against 160 h capacity.
```

The last line is the part that gets acted on, and it is derived by grouping nonzero slacks by resource-month and listing which projects' hard minimums contribute.

**IIS as a secondary tool.** An irreducible infeasible subsystem is more rigorous and less readable. Provide it behind `--iis` for the analyst, not in the default path. HiGHS and Gurobi both support it; CBC does not.

## Performance

| Lever | Effect | When to reach for it |
|---|---|---|
| Restrict `E` via `eligible` | Cuts variables and binaries proportionally | First. Always. Most pairs are never real. |
| Drop `y` where `hmin = 0` and no fragmentation limit | Removes binaries entirely for those cells | When binaries dominate solve time |
| MIP gap tolerance of 0.5 to 1 percent | Large speedup, negligible plan difference | Routine. Optimality to the penny is meaningless when rates are estimates. |
| Warm start from baseline | Faster convergence, better incumbents early | Routine, once a baseline exists |
| Rolling horizon | Solve 12 months, freeze the first 3, roll | Only past roughly 100k cells |
| Fix closed months by bound rather than constraint | Presolve eliminates them | Routine |

Set a wall-clock limit (300 s default). On timeout, return the incumbent with its proven gap and flag the result as not optimal. A 1 percent gap plan delivered in a minute beats a proven optimum nobody waited for.

## Testing the model

Property tests matter more than example tests here, because the failure mode is a subtly wrong plan rather than a crash.

- **Feasibility monotonicity:** relaxing any bound never worsens the optimal objective.
- **Capacity respected:** no person exceeds `cap` in any month, in any returned solution.
- **Semi-continuity:** every nonzero `x` is at least its `hard_min`.
- **Fixed cells honored:** locked and closed-month cells match input exactly.
- **Churn sanity:** re-solving with unchanged inputs returns the baseline unchanged.
- **Rate agreement:** Python `loaded_rate()` matches the Grist formula across the full structure cross product.

The churn test is the regression canary. If it starts failing, either the model became degenerate or someone removed the stability term.
