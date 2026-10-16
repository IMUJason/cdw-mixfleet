# -*- coding: utf-8 -*-
"""C3: LTL 每访问站点固定装卸时间敏感性 —— 审稿意见 Q1 的定量回应。
M 实例(seed 42), P.LTL_STOP_H ∈ {0(对照), 0.1, 0.2}(h/站, 即 6/12 分钟):
重解 exact(CPLEX 900s/1e-3) + SA(固定迭代)+reprice, 记录模式结构与趟数,
对照基准(表3 M 行: CPLEX 22275 / SA 22359)。
验证: 每站固定装卸是否显著改变成本与分装/多站穿越的盈利性, 混派结论是否稳健。
输出 results/tables/ltl_stop_sens.csv。"""
import os, sys, csv, time
sys.path.insert(0, os.path.dirname(__file__))
import params as P
P.LTL_STOP_H = float(sys.argv[1]) if len(sys.argv) > 1 else 0.1
import mixfleet_model as MF, mixfleet_heuristic as MH
import inst_config as CFG, reprice as RP

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TBL = os.path.join(ROOT, "results", "tables")
OUT = os.path.join(TBL, "ltl_stop_sens.csv")
TAG = "M"


def structure(inst, ft, lr):
    ftl_only = ltl_only = mixed = idle = 0
    for v in range(inst["n_vehicles"]):
        has_f = any(n > 0 for (vv, _), n in ft.items() if vv == v)
        has_l = any(r for r in lr.get(v, []))
        if has_f and has_l: mixed += 1
        elif has_f: ftl_only += 1
        elif has_l: ltl_only += 1
        else: idle += 1
    n_ftl = sum(n for n in ft.values() if n > 0)
    n_ltl = sum(len([r for r in ts if r]) for ts in lr.values())
    return ftl_only, ltl_only, mixed, idle, n_ftl, n_ltl


def main():
    inst = CFG.gen(TAG, 42)
    t0 = time.time()
    m, _ = MF.build_mip(inst, time_limit=900, gap=1e-3)
    wt = time.time() - t0
    rep = MF.solver_report(m)
    print(f"[stop={P.LTL_STOP_H}] exact: {rep['status']} inc {rep['incumbent']:.0f} "
          f"bound {rep['bound']:.0f} ({wt:.0f}s)", flush=True)
    t0 = time.time()
    ft, lr, hc, hm = MH.solve(inst, time_limit=CFG.SA_TIME[TAG], seed=42,
                              max_iters=CFG.SA_ITERS.get(TAG))
    sa_t = time.time() - t0
    rc, rstat = RP.reprice(inst, ft, lr)
    print(f"[stop={P.LTL_STOP_H}] SA: reprice {rc:.0f} ({rstat}, {hm['iters']} it, {sa_t:.0f}s)",
          flush=True)
    s = structure(inst, ft, lr)
    print(f"[stop={P.LTL_STOP_H}] structure F/L/mixed/idle {s[0]}/{s[1]}/{s[2]}/{s[3]}, "
          f"FTL trips {s[4]}, LTL routes {s[5]}", flush=True)

    row = {"instance": TAG, "ltl_stop_h": P.LTL_STOP_H,
           "cpx_status": rep["status"], "cpx_incumbent": f"{rep['incumbent']:.0f}",
           "cpx_bound": f"{rep['bound']:.0f}", "cpx_time_s": f"{wt:.0f}",
           "sa_reprice": f"{rc:.0f}", "sa_time_s": f"{sa_t:.0f}",
           "ftl_only": s[0], "ltl_only": s[1], "mixed": s[2], "idle": s[3],
           "n_ftl_trips": s[4], "n_ltl_routes": s[5]}
    existed = os.path.exists(OUT)
    with open(OUT, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not existed:
            w.writeheader()
        w.writerow(row)
    print("row appended ->", OUT, flush=True)


if __name__ == "__main__":
    main()
