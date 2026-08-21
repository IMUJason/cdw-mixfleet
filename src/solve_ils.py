#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ILS 基线: python solve_ils.py instances/S.csv --seed 42 --cycles 418
默认随后做精确重定价(reprice: 结构固定/载荷自由 LP, 与 SA 同报告口径)。
论文固定周期数(标定运行记录后固定重跑): S 418 / M 194 / L 121 / X 47 / XL 50
(XL 用 --seed 7, 与论文一致)。"""
import os, sys, time, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plan_io as PIO
import ils as ILS
from instance_io import load_instance

PAPER_CYCLES = {"S": 418, "M": 194, "L": 121, "X": 47, "XL": 50}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", help="instance CSV (e.g. instances/S.csv)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--cycles", type=int, default=None,
                    help="fixed perturbation-descent cycle budget "
                         "(paper budgets: S 418 / M 194 / L 121 / X 47 / XL 50)")
    ap.add_argument("--time", type=float, default=None,
                    help="wall-clock safety cap s (default 2.5x the paper budget by instance)")
    ap.add_argument("--no-reprice", action="store_true", help="skip exact re-pricing")
    ap.add_argument("--calibrate", type=float, default=None, metavar="S",
                    help="calibration mode: run for S seconds of wall clock and report the "
                         "cycle count reached (the paper's protocol for fixing the budget)")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    inst = load_instance(a.instance)
    tag = os.path.splitext(os.path.basename(a.instance))[0]
    if a.time is None:
        cap = {"S": 75, "M": 150, "L": 225, "X": 300, "XL": 450}.get(tag, 600)
    else:
        cap = a.time
    cycles = a.cycles if a.cycles is not None else PAPER_CYCLES.get(tag)
    if a.calibrate is not None and cycles is None:
        cycles = None
    elif cycles is None:
        sys.exit(f"unknown instance tag '{tag}': pass --cycles explicitly")

    t0 = time.time()
    if a.calibrate is not None:
        _, _, c_eval, n_it, wt = ILS.run_ils(inst, seed=a.seed, budget_s=a.calibrate)
        print(f"[{tag}] ILS calibrate seed={a.seed} cycles={n_it} in {wt:.1f}s "
              f"(rerun with --cycles {n_it - 1} for the fixed-budget protocol)")
        return
    ft, lr, c_eval, n_it, wt = ILS.run_ils(inst, seed=a.seed, max_iters=cycles)
    if wt > cap:
        print(f"[{tag}] warning: fixed cycles exceeded the wall-clock cap")
    line = f"[{tag}] ILS seed={a.seed} cycles={n_it} evaluate={c_eval:.2f} time={wt:.1f}s"
    cost = c_eval
    if not a.no_reprice:
        import reprice as RP
        rc, st = RP.reprice(inst, ft, lr)
        if rc is not None:
            cost = rc
            line += f" | reprice={rc:.2f} ({st})"
    print(line)

    outdir = a.out or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "out")
    os.makedirs(outdir, exist_ok=True)
    plan = os.path.join(outdir, f"{tag}_ils_plan.csv")
    PIO.save_plan(plan, ft, lr, dict(
        method="ils", instance=tag, seed=a.seed, cycles=n_it,
        evaluate=f"{c_eval:.2f}", reported_cost=f"{cost:.2f}", time_s=f"{wt:.1f}"))
    print("plan ->", plan)


if __name__ == "__main__":
    main()
