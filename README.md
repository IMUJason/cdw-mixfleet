# CDW-MixFleet — Replication Package

Replication package for **"Full-truckload and less-than-truckload mixed dispatch
of construction and demolition waste under a limited, class-licensed fleet"**
(submitted to *Transportation Research Part E*).

It contains everything needed to reproduce the paper's computational results:

- **`instances/`** — five self-contained instance files (**one CSV per instance**),
  each with demand sites (class, tonnage, coordinates), class-compliant sinks
  (fees, recycling revenues), the class-licensed fleet, the frozen full driving
  distance matrix, and a snapshot of all solve-time parameters. These CSVs are
  the frozen ground truth: results do **not** depend on re-generating instances.
- **`src/`** — the exact model (MILP with tonnage-flow strengthening), the two
  metaheuristics benchmarked in the paper (fixed-iteration simulated annealing
  and a textbook iterated local search), the exact plan re-pricer, and
  command-line entry points.
- **`results_reference.csv`** — the paper's benchmark-table reference numbers
  (exact vs. SA) to compare your runs against, including the fixed SA iteration
  budgets.
- **`src/gen_scale.py`** — regenerates the paper's two instance families
  bit-for-bit (fixed seeds): fresh demand draws from the same generator on the
  same network, fleets sized automatically per draw (the sizing rule
  reproduces the hand-calibrated S/M/L fleets within one vehicle), with a
  single-site LTL-dominance screen. Family members are addressed by
  `(n_ftl, n_ltl, seed)`; the per-member coordinates are in the family
  reference CSVs.
- **`results_reference/`** — the reference CSVs behind **every other reported
  table and experiment** (five-seed robustness, component and per-operator
  ablations, ILS baseline, LP-relaxation gaps, MTZ redundancy, sensitivity and
  counterfactual studies, dispatch structure decomposition, alignment check).

Distances were queried from the Amap (autoNavi) API; see `NOTICE`.

## Install

```bash
pip install -r requirements.txt      # pulp, numpy
# optional but recommended: CPLEX (e.g. community edition) -> exact solver
# without CPLEX the code falls back to CBC (bundled with pulp)
```

## Quickstart

```bash
cd src

# Exact solve (CPLEX if installed, else CBC):
python solve_exact.py ../instances/S.csv --time 300 --gap 0.001
# -> status=Optimal incumbent=14608.22 bound=14593.62 mip_gap=0.1% ...

# SA metaheuristic at the paper's fixed iteration budget, then exact re-pricing:
python solve_sa.py ../instances/S.csv --seed 42 --iters 158299
# -> [S] SA seed=42 iters=158299 evaluate=14627.11 ... | reprice=14627.11 (Optimal)

# ILS baseline at the paper's fixed cycle budget (same evaluation protocol):
python solve_ils.py ../instances/S.csv --seed 42
# -> [S] ILS seed=42 cycles=418 evaluate=14628 ... | reprice=14628.xx (Optimal)

# Root LP relaxation of either formulation (LP-gap experiment):
python solve_exact.py ../instances/S.csv --lp-relax            # tonnage-flow strengthened
python solve_exact.py ../instances/S.csv --lp-relax --no-flow  # compact MTZ-only
# -> [S] LP-relax (strengthened) status=Optimal lp_obj=13011.2 ...
# -> [S] LP-relax (compact)     status=Optimal lp_obj=6686.8  ...

# Formulation switches for full MIPs (MTZ-redundancy experiment):
python solve_exact.py ../instances/S.csv --no-mtz --time 300
# -> same incumbent/bound as the strengthened formulation

# Independently re-price any saved plan (exact report basis of the paper):
python solve_reprice.py ../instances/S.csv ../out/S_sa_plan.csv
```

## Reproducing the paper's benchmark table

Fixed SA iteration budgets (from `results_reference.csv`):

| Instance | iters | expected SA cost (re-priced) | expected exact (time limit) |
|---|---|---|---|
| S  | 158,299 | 14,627 | 14,608 (300 s, gap 0.1%) |
| M  | 190,378 | 22,359 | 22,275 (900 s, gap 1.7%) |
| L  | 228,809 | 25,175 | 24,865 (1200 s, gap 2.6%) |
| X  | 178,709 | 30,072 | 29,780 (1800 s, gap 3.6%) |
| XL | 171,860 | 55,764 | 54,727 (1800 s, gap 4.9%) |

The SA stops at the **iteration budget** (bit-for-bit reproducible regardless of
machine load) with a wall-clock cap of ~1.5x the reference time. Seed 42 (XL:
seed 7) with the budget above reproduces the table exactly.

The ILS baseline uses the same protocol with budgets denominated in
perturbation–descent cycles: S 418 / M 194 / L 121 / X 47 / XL 50 (seed 42,
XL seed 7; defaults of `solve_ils.py`). `--calibrate <seconds>` reruns the
wall-clock calibration run that fixed these counts.

Ablation switches for `solve_sa.py` (paper ablation experiments):
`--disable-op rar` and `--no-restart` for the component ablation; any single
operator can be disabled for the per-operator ablation
(`rar/insert/drop/relocate/swap/merge/twopt/ftl`).

## Reference results for the other tables

Every number reported in the paper traces to one of the CSVs in
`results_reference/`:

| Paper result | Reference CSV |
|---|---|
| Evaluator alignment (both directions) | `alignment_check.csv` |
| Root LP-relaxation gaps (compact vs. strengthened) | `lp_gaps.csv` |
| MTZ redundancy (strengthened MIP without MTZ) | `mtz_redundancy.csv` |
| Five-seed robustness (S, M) | `mixfleet_seeds.csv`, `mixfleet_seeds_agg.csv` |
| **Instance families** (certified 10 + large 10, paper family section) | `scale_family_small.csv`, `scale_family_large.csv` (screening log: `scale_family_screen.csv`) |
| SA component ablation (no ruin-and-recreate / no restart) | `ablation.csv` |
| Per-operator ablation (9 variants × 5 instances) | `ablation_ops.csv` |
| ILS baseline and the scale crossover | `baseline_ils.csv` |
| Parameter sensitivity (trip fee, night window, penalty) | `sensitivity_mixfleet.csv` |
| Symmetric FTL handling time (+0.5 h/trip) | `ftl_handling_sens.csv` |
| Shortage-penalty counterfactual (π = 50 / 500) | `pi_counterfactual.csv` |
| Dispatch structure decomposition | `structure_stats.csv` |
| Forced single-mode counterfactuals | `mode_counterfactual.csv` |

Exact/SA numbers for all five instances: `results_reference.csv` (root).

## Reporting basis (important)

Both metaheuristics' internal evaluator assigns loads first-fit within each
route; the **reported** cost of every SA and ILS plan is its *exact re-priced*
value — the plan's structure fixed inside the MILP with load variables free,
solved as an LP. All solvers share one evaluator this way (`solve_sa.py` and
`solve_ils.py` do it automatically; `solve_reprice.py` re-checks any saved plan).

## Files

```
instances/S.csv M.csv L.csv X.csv XL.csv   # frozen instances (incl. distance matrices)
data/external/dongsheng_real_network.json  # queried Amap network (anchors + driving matrix);
                                           #   required by the family generator (NOTICE applies)
src/params.py              # cost parameters with provenance IDs (P01-P10)
src/instance_io.py         # instance CSV export/load (round-trip exact)
src/mixfleet_model.py      # MILP: tonnage-flow strengthened formulation
                           #   (+ --no-flow / --no-mtz formulation switches)
src/mixfleet_heuristic.py  # SA (fixed-iteration budgets, 8 neighborhoods)
src/ils.py                 # ILS baseline (descent + perturbation, fixed cycles)
src/reprice.py             # exact plan re-pricing (structure fixed, loads free)
src/solve_exact.py         # CLI: exact solve (+ LP relaxation / formulation switches)
src/solve_sa.py            # CLI: SA (+auto reprice, ablation switches)
src/solve_ils.py           # CLI: ILS (+auto reprice, calibration mode)
src/solve_reprice.py       # CLI: re-price a saved plan
src/plan_io.py             # dispatch-plan CSV format
src/gen_scale.py           # instance-family generator (fixed seeds, auto fleet
                           #   calibrated to the paper's fleets, LTL dominance screen)
results_reference.csv      # benchmark-table reference numbers (root)
results_reference/         # reference CSVs for all other tables
NOTICE                     # data attribution (Amap)
```

## Citation

If you use this package, please cite the paper (citation entry will be added
upon publication).
