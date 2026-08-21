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
- **`src/`** — the exact model (MILP with tonnage-flow strengthening), the
  simulated-annealing metaheuristic, and the exact plan re-pricer, plus three
  command-line entry points.
- **`results_reference.csv`** — the paper's reference numbers (Table 2) to
  compare your runs against, including the fixed SA iteration budgets.

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

# Independently re-price any saved plan (exact report basis of the paper):
python solve_reprice.py ../instances/S.csv ../out/S_sa_plan.csv
```

## Reproducing the paper's Table 2

Fixed SA iteration budgets (from `results_reference.csv`):

| Instance | iters | expected SA cost (re-priced) | expected exact (time limit) |
|---|---|---|---|
| S  | 158,299 | 14,627 | 14,608 (300 s, gap 0.1%) |
| M  | 190,378 | 22,359 | 22,275 (900 s, gap 1.7%) |
| L  | 228,809 | 25,175 | 24,865 (1200 s, gap 2.6%) |
| X  | 178,709 | 30,072 | 29,780 (1800 s, gap 3.6%) |
| XL | 171,860 | 55,764 | 54,727 (1800 s, gap 4.9%) |

The SA stops at the **iteration budget** (bit-for-bit reproducible regardless of
machine load) with a wall-clock cap of ~1.5x the reference time. Seed 42 with the
budget above reproduces the table exactly.

Ablation switches (paper Sec. 6, ablation table):
`--disable-op rar` (no ruin-and-recreate) and `--no-restart`.

## Reporting basis (important)

The SA's internal evaluator assigns loads first-fit within each route; the
**reported** cost of every SA plan is its *exact re-priced* value — the plan's
structure fixed inside the MILP with load variables free, solved as an LP. All
three solvers share one evaluator this way (`solve_sa.py` does it automatically;
`solve_reprice.py` re-checks any saved plan).

## Files

```
instances/S.csv M.csv L.csv X.csv XL.csv   # frozen instances (incl. distance matrices)
src/params.py              # cost parameters with provenance IDs (P01-P10)
src/instance_io.py         # instance CSV export/load (round-trip exact)
src/mixfleet_model.py      # MILP: tonnage-flow strengthened formulation
src/mixfleet_heuristic.py  # SA (fixed-iteration budgets, 8 neighborhoods)
src/reprice.py             # exact plan re-pricing (structure fixed, loads free)
src/solve_exact.py         # CLI: exact solve
src/solve_sa.py            # CLI: SA (+auto reprice, ablation switches)
src/solve_reprice.py       # CLI: re-price a saved plan
src/plan_io.py             # dispatch-plan CSV format
results_reference.csv      # paper Table 2 reference numbers
NOTICE                     # data attribution (Amap)
```

## Citation

If you use this package, please cite the paper (citation entry will be added
upon publication).
