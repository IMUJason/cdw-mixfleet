# -*- coding: utf-8 -*-
"""E2 对称计时补充: S/L/X/XL 的对称混合基准解(FTL_SVC_H=0.5)。
M 已有(ftl_handling_sens.csv: 23,692)。输出 results/tables/mixed_sym.csv。
用途: 对称口径下 restricted vs mixed 的同口径(within-regime)溢价。"""
import os, sys, csv, time
sys.path.insert(0, os.path.dirname(__file__))
import params as P
P.FTL_SVC_H = 0.5
import mixfleet_model as MF, mixfleet_heuristic as MH
import inst_config as CFG, reprice as RP
import run_mode_restricted as MR

TBL = os.path.join(CFG.ROOT, "results", "tables")
OUT = os.path.join(TBL, "mixed_sym.csv")


def main():
    FIELDS = ["instance", "cpx_incumbent", "cpx_bound", "cpx_gap_pct", "cpx_time_s", "note"]
    rows = [dict(instance="M", cpx_incumbent="23692", cpx_bound="", cpx_gap_pct="",
                 cpx_time_s="", note="from ftl_handling_sens.csv")]
    for tag in ["S", "L", "X", "XL"]:
        inst = MR.gen_inst(tag)
        lim = CFG.CPLEX_LIMIT.get(tag, 1800)
        print(f"=== [sym-mixed] {tag} CPLEX {lim}s ===", flush=True)
        t0 = time.time()
        m, _ = MF.build_mip(inst, time_limit=lim, gap=CFG.GAP_TOL)
        wt = time.time() - t0
        rep = MF.solver_report(m)
        print(f"  exact: {rep['status']} inc {rep['incumbent']:.0f} bound {rep['bound']:.0f} "
              f"gap {rep['mip_gap_pct']}% ({wt:.0f}s)", flush=True)
        rows.append(dict(instance=tag, cpx_incumbent=f"{rep['incumbent']:.0f}",
                         cpx_bound=f"{rep['bound']:.0f}", cpx_gap_pct=rep["mip_gap_pct"],
                         cpx_time_s=f"{wt:.0f}", note=""))
        with open(OUT, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
            w.writeheader(); w.writerows(rows)
    print("saved ->", OUT, flush=True)


if __name__ == "__main__":
    main()
