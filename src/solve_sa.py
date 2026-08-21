#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""SA 元启发式: python solve_sa.py instances/S.csv --seed 42 --iters 158299
默认随后做精确重定价(reprice: 结构固定/载荷自由 LP, 与论文报告口径一致)。
消融: --disable-op rar / --no-restart (论文消融实验的复现开关)。"""
import os, sys, time, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import instance_io as IO
import plan_io as PIO
import mixfleet_heuristic as MH
from instance_io import load_instance


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", help="instance CSV (e.g. instances/S.csv)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--iters", type=int, required=True,
                    help="fixed iteration budget (paper budgets: see results_reference.csv)")
    ap.add_argument("--time", type=float, default=None,
                    help="wall-clock cap s (default 1.5x the reference SA budget by instance)")
    ap.add_argument("--no-reprice", action="store_true", help="skip exact re-pricing")
    ap.add_argument("--disable-op", default=None,
                    help="ablation: operator to disable (rar/insert/drop/relocate/swap/merge/twopt/ftl)")
    ap.add_argument("--no-restart", action="store_true", help="ablation: disable restart-from-best")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    inst = load_instance(a.instance)
    tag = os.path.splitext(os.path.basename(a.instance))[0]
    if a.time is None:
        cap = {"S": 45, "M": 90, "L": 135, "X": 180, "XL": 270}.get(tag, 600)
    else:
        cap = a.time
    dis = {a.disable_op} if a.disable_op else None

    t0 = time.time()
    ft, lr, hc, hm = MH.solve(inst, time_limit=cap, seed=a.seed, max_iters=a.iters,
                              disable_ops=dis, use_restart=not a.no_restart)
    ht = time.time() - t0
    line = f"[{tag}] SA seed={a.seed} iters={hm['iters']} evaluate={hc:.2f} time={ht:.1f}s"
    cost = hc
    if not a.no_reprice:
        import reprice as RP
        rc, st = RP.reprice(inst, ft, lr)
        if rc is not None:
            cost = rc
            line += f" | reprice={rc:.2f} ({st})"
    print(line)

    outdir = a.out or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "out")
    os.makedirs(outdir, exist_ok=True)
    plan = os.path.join(outdir, f"{tag}_sa_plan.csv")
    PIO.save_plan(plan, ft, lr, dict(
        method="sa", instance=tag, seed=a.seed, iters=hm["iters"],
        evaluate=f"{hc:.2f}", reported_cost=f"{cost:.2f}",
        disabled_op=a.disable_op or "", restart=str(not a.no_restart),
        time_s=f"{ht:.1f}"))
    print("plan ->", plan)


if __name__ == "__main__":
    main()
