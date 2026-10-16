# -*- coding: utf-8 -*-
"""E2 对称计时第二轮: FTL_SVC_H=0.5 下重跑模式受限反事实(5 实例×2 模式)。
输出 results/tables/mode_restricted_sym.csv, 与基准口径 mode_restricted.csv 对照。"""
import os, sys, csv, time, copy
sys.path.insert(0, os.path.dirname(__file__))
import params as P
P.FTL_SVC_H = 0.5                      # 对称装卸口径(每趟 FTL +0.5h)
import mixfleet_model as MF, mixfleet_heuristic as MH
import inst_config as CFG, reprice as RP
import run_mode_restricted as MR

TBL = os.path.join(CFG.ROOT, "results", "tables")
OUT = os.path.join(TBL, "mode_restricted_sym.csv")


def sym_mixed_ref():
    """对称口径的混合参照: 来自 ftl_handling_sens.csv(M) — 其余实例对称口径混合解不存在,
    报告时以受限解对'基准混合 incumbent'的溢价并注明计时口径差异。此处先落盘原始数。"""
    return {}


def main():
    rows = []
    for tag in ["S", "M", "L", "X", "XL"]:
        base = MR.gen_inst(tag)
        lim = CFG.CPLEX_LIMIT.get(tag, 1800)
        stime = CFG.SA_TIME.get(tag, 180)
        siters = CFG.SA_ITERS.get(tag)
        for mode in ("ftl", "ltl"):
            inst = MR.restrict(base, mode)
            print(f"=== [sym] {tag} all-{mode.upper()} CPLEX {lim}s ===", flush=True)
            t0 = time.time()
            m, _ = MF.build_mip(inst, time_limit=lim, gap=CFG.GAP_TOL)
            wt = time.time() - t0
            rep = MF.solver_report(m)
            print(f"  exact: {rep['status']} inc {rep['incumbent'] and round(rep['incumbent'])} "
                  f"bound {rep['bound'] and round(rep['bound'])} ({wt:.0f}s)", flush=True)
            t0 = time.time()
            ft, lr, hc, hm = MH.solve(inst, time_limit=stime, seed=42, max_iters=siters)
            rc, rstat = RP.reprice(inst, ft, lr)
            with open(os.path.join(TBL, "mixfleet_bench.csv"), encoding="utf-8-sig") as fh:
                mx = next(r for r in csv.DictReader(fh) if r["instance"].startswith(tag + ":"))
            prem = 100.0 * (rep["incumbent"] - float(mx["cpx_cost"])) / float(mx["cpx_cost"]) if rep["incumbent"] else None
            rows.append(dict(instance=tag, mode=f"all-{mode}",
                             cpx_status=rep["status"],
                             cpx_incumbent=f"{rep['incumbent']:.0f}" if rep["incumbent"] else "",
                             cpx_bound=f"{rep['bound']:.0f}" if rep["bound"] else "",
                             cpx_gap_pct=rep["mip_gap_pct"], cpx_time_s=f"{wt:.0f}",
                             sa_reprice=f"{rc:.0f}", reprice_status=rstat,
                             base_mixed_incumbent=mx["cpx_cost"],
                             premium_vs_base_mixed_pct=f"{prem:.2f}" if prem is not None else ""))
            print(f"  SA: {rc:.0f} ({rstat}) | premium vs base-mixed {prem and round(prem,2)}%", flush=True)
            with open(OUT, "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                w.writeheader(); w.writerows(rows)
    print("saved ->", OUT, flush=True)


if __name__ == "__main__":
    main()
