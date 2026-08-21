#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""精确求解(CPLEX 优先, 无则 CBC): python solve_exact.py instances/S.csv --time 300 --gap 0.001
输出: 终端打印 incumbent/bound/gap; out/<tag>_exact_plan.csv 为调度方案(可被 solve_reprice.py 复核)。"""
import os, sys, time, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import instance_io as IO
import plan_io as PIO
import mixfleet_model as MF
from instance_io import load_instance


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", help="instance CSV (e.g. instances/S.csv)")
    ap.add_argument("--time", type=float, default=300.0, help="wall-clock limit s (default 300)")
    ap.add_argument("--gap", type=float, default=1e-3, help="relative MIP gap tolerance (default 0.001)")
    ap.add_argument("--out", default=None, help="output dir (default out/)")
    a = ap.parse_args()

    inst = load_instance(a.instance)
    tag = os.path.splitext(os.path.basename(a.instance))[0]
    t0 = time.time()
    m, vv = MF.build_mip(inst, time_limit=a.time, gap=a.gap)
    ct = time.time() - t0
    rep = MF.solver_report(m)
    print(f"[{tag}] status={rep['status']} incumbent={rep['incumbent']:.2f} "
          f"bound={rep['bound']:.2f} mip_gap={rep['mip_gap_pct']}% time={ct:.1f}s")

    # 提取方案(与主库 verify_alignment.extract_dispatch 同逻辑)
    import pulp
    from mixfleet_model import get_veh_classes, sink_for_class
    ftl_ntrip = {}
    for (v, fid), var in vv["ntr_f"].items():
        val = pulp.value(var) or 0.0
        if val >= 0.5:
            ftl_ntrip[(v, fid)] = int(round(val))
    z = vv["z"]; depot = inst["depot_idx"]
    node2ltl = {node: lid for lid, node in enumerate(inst["ltl_idx"])}
    veh_cls = get_veh_classes(inst)
    ltl_routes = {v: [] for v in range(inst["n_vehicles"])}
    vs_ts = sorted({(v, t) for (v, t, i, j) in z.keys()})
    for v, t in vs_ts:
        cur = depot; route = []
        while True:
            nxt = None
            for (vv_, tt, i, j) in z.keys():
                if vv_ == v and tt == t and i == cur and j != cur and (pulp.value(z[v, t, i, j]) or 0) > 0.5:
                    nxt = j; break
            if nxt is None or nxt == depot:
                break
            if nxt in node2ltl:
                route.append(node2ltl[nxt]); cur = nxt
            else:
                break
        if route:
            ltl_routes[v].append(route)

    outdir = a.out or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "out")
    os.makedirs(outdir, exist_ok=True)
    plan = os.path.join(outdir, f"{tag}_exact_plan.csv")
    PIO.save_plan(plan, ftl_ntrip, ltl_routes, dict(
        method="exact", instance=tag, status=rep["status"],
        cost=f"{rep['incumbent']:.2f}", bound=f"{rep['bound']:.2f}",
        mip_gap_pct=rep["mip_gap_pct"], time_s=f"{ct:.1f}"))
    print("plan ->", plan)


if __name__ == "__main__":
    main()
