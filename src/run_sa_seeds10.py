# -*- coding: utf-8 -*-
"""E5(R1.3): S/M/L/X 各 10 种子的 SA 稳健性 —— 双离散度口径。
同实例搜索种子(mixfleet_seeds 已有 5 个: 42/7/13/99/2024 为需求种子口径!)
注意: mixfleet_seeds.csv 的种子是"需求种子"(每种子重生成实例), 不是 SA 随机性;
SA 随机性=同实例(需求 seed 42 固定)不同 SA seed。本脚本跑后者: SA seed 0..9,
报 gap_inc 均值/最差/标准差, 与 sa_restarts.csv(5 次)衔接扩到 10。"""
import os, sys, csv, time, statistics
sys.path.insert(0, os.path.dirname(__file__))
import params as P
import mixfleet_heuristic as MH
import inst_config as CFG, reprice as RP
import run_mode_restricted as MR

TBL = os.path.join(CFG.ROOT, "results", "tables")
OUT = os.path.join(TBL, "sa_seeds10.csv")
SEEDS = list(range(10))


def main():
    rows = []
    for tag in ["S", "M", "L", "X"]:
        inst = MR.gen_inst(tag)
        stime = CFG.SA_TIME.get(tag, 120)
        siters = CFG.SA_ITERS.get(tag)
        with open(os.path.join(TBL, "mixfleet_bench.csv"), encoding="utf-8-sig") as fh:
            mx = next(r for r in csv.DictReader(fh) if r["instance"].startswith(tag + ":"))
        cpx = float(mx["cpx_cost"])
        gaps = []
        for sd in SEEDS:
            ft, lr, hc, hm = MH.solve(inst, time_limit=stime, seed=sd, max_iters=siters)
            rc, st = RP.reprice(inst, ft, lr)
            g = 100.0 * (rc - cpx) / cpx
            gaps.append(g)
            rows.append(dict(instance=tag, sa_seed=sd, reprice=f"{rc:.0f}", status=st,
                             cpx_incumbent=cpx, gap_inc_pct=f"{g:.3f}"))
            print(f"{tag} seed {sd}: {rc:.0f} gap {g:.3f}%", flush=True)
        print(f"{tag}: mean {statistics.mean(gaps):.3f} worst {max(gaps):.3f} std {statistics.stdev(gaps):.3f}", flush=True)
        with open(OUT, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader(); w.writerows(rows)
    print("saved ->", OUT, flush=True)


if __name__ == "__main__":
    main()
