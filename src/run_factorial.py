# -*- coding: utf-8 -*-
"""E3(R2.9): M 上两组 2x2 因子实验(夜间窗 H x 缺货惩罚 pi; 车队规模 x 固定出车费 F_trip)。
每格三政策(mixed/all-FTL/all-LTL)CPLEX 精确解(基准上限 900s), SA 同预算可选后补。
输出 results/tables/factorial.csv"""
import os, sys, csv, time, copy
sys.path.insert(0, os.path.dirname(__file__))
import params as P
import mixfleet_model as MF
import inst_config as CFG
import run_mode_restricted as MR

TBL = os.path.join(CFG.ROOT, "results", "tables")
OUT = os.path.join(TBL, "factorial.csv")
BASE_H, BASE_PI, BASE_F = P.NIGHT_HOURS, P.SHORTAGE_PENALTY, P.TRIP_FIXED
BASE_COUNTS = None

CELLS = []
for h in (6, 10):
    for pi in (50, 500):
        CELLS.append(dict(design="Hxp", H=h, pi=pi, F=BASE_F, fleet_scale=1.0))
for scale in (0.8, 1.2):
    for f in (200, 600):
        CELLS.append(dict(design="fleetxF", H=BASE_H, pi=BASE_PI, F=f, fleet_scale=scale))


def scaled_inst(cell):
    base = MR.gen_inst("M")
    inst = copy.deepcopy(base)
    if cell["fleet_scale"] != 1.0:
        vc = base["veh_classes"]
        keep = int(round(len(vc) * cell["fleet_scale"]))
        if keep <= len(vc):
            inst["veh_classes"] = vc[:keep]
        else:
            # 放大: 循环补充保持类别比例(固定整数规则, 不重新按需求配车)
            import itertools
            inst["veh_classes"] = [vc[i % len(vc)] for i in range(keep)]
        inst["n_vehicles"] = keep
    return inst


def main():
    global BASE_COUNTS
    rows = []
    for cell in CELLS:
        P.NIGHT_HOURS = cell["H"]
        P.SHORTAGE_PENALTY = cell["pi"]
        P.TRIP_FIXED = cell["F"]
        for mode in ("mixed", "ftl", "ltl"):
            inst = MR.gen_inst("M") if mode == "mixed" else MR.restrict(MR.gen_inst("M"), mode)
            if cell["fleet_scale"] != 1.0:
                inst = scaled_inst(cell) if mode == "mixed" else MR.restrict(scaled_inst(cell), mode)
            t0 = time.time()
            m, _ = MF.build_mip(inst, time_limit=900, gap=CFG.GAP_TOL)
            wt = time.time() - t0
            rep = MF.solver_report(m)
            print(f"[{cell['design']}] H{cell['H']} pi{cell['pi']} F{cell['F']} x{cell['fleet_scale']} "
                  f"{mode}: {rep['status']} inc {rep['incumbent'] and round(rep['incumbent'])} "
                  f"bound {rep['bound'] and round(rep['bound'])} ({wt:.0f}s)", flush=True)
            rows.append(dict(design=cell["design"], H=cell["H"], pi=cell["pi"], F_trip=cell["F"],
                             fleet_scale=cell["fleet_scale"], mode=mode,
                             cpx_status=rep["status"],
                             cpx_incumbent=f"{rep['incumbent']:.0f}" if rep["incumbent"] else "",
                             cpx_bound=f"{rep['bound']:.0f}" if rep["bound"] else "",
                             cpx_gap_pct=rep["mip_gap_pct"], cpx_time_s=f"{wt:.0f}"))
            with open(OUT, "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                w.writeheader(); w.writerows(rows)
    print("saved ->", OUT, flush=True)


if __name__ == "__main__":
    main()
