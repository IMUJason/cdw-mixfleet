# -*- coding: utf-8 -*-
"""E1 正式: ALNS calibrate-then-fixed 二跑 + 两族 20 实例 x 3 种子。
校准: 每实例墙钟标定记录迭代数; 正式: 固定迭代重跑(可复现)。
输出 results/tables/alns_family.csv"""
import os, sys, csv, copy
sys.path.insert(0, os.path.dirname(__file__))
import run_alns as A, reprice as RP
import inst_config as CFG

TBL = os.path.join(CFG.ROOT, "results", "tables")
OUT = os.path.join(TBL, "alns_family.csv")
SEEDS = [42, 7, 13]


def gen_family(fam, size_id, seed, nf, nl, veh_desc):
    """族实例生成器(与 scale_study 同口径): gen_scale_instance(nf, nl, seed)。"""
    from scale_study.gen_scale import gen_scale_instance
    return gen_scale_instance(nf, nl, seed)


def main():
    rows = []
    for name in ("scale_small_final", "scale_large"):
        path = os.path.join(CFG.ROOT, "results", "scale_study", name + ".csv")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8-sig") as fh:
            members = list(csv.DictReader(fh))
        for r in members:
            sid = r["size_id"]
            try:
                inst = gen_family(name, sid, int(r["seed"]), int(r["nf"]), int(r["nl"]), r["veh"])
            except Exception as e:
                print("GEN-FAIL", sid, e, flush=True)
                continue
            budget = 60 if name == "scale_small_final" else 180
            ft, lr, hc, hm, wt = A.solve_alns(inst, time_limit=budget, seed=42, max_iters=None)
            calib_iters = hm["iters"]
            for sd in SEEDS:
                ft, lr, hc, hm, wt = A.solve_alns(inst, time_limit=budget, seed=sd,
                                                  max_iters=calib_iters)
                rc, st = RP.reprice(inst, ft, lr)
                rows.append(dict(family=name, size_id=sid, sa_seed=sd, reprice=f"{rc:.0f}",
                                 status=st, time_s=f"{wt:.0f}", iters=hm["iters"],
                                 calib_iters=calib_iters, cpx_incumbent=r["cpx_incumbent"],
                                 cpx_bound=r["cpx_bound"], sa_reprice=r["sa_reprice"],
                                 ils_reprice=r["ils_reprice"]))
                print(f"{sid} seed {sd}: {rc:.0f} ({st})", flush=True)
                with open(OUT, "w", newline="", encoding="utf-8") as fh:
                    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                    w.writeheader(); w.writerows(rows)
    print("saved ->", OUT, flush=True)


if __name__ == "__main__":
    main()
