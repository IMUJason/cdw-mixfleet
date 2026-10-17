# -*- coding: utf-8 -*-
"""ALNS education 消融(补救2): use_polish=False 下 S/M/X/XL 对照。
目的: 判断 XL 迭代饥饿的主因是否为全枚举 education 开销, 属自加组件消融, 非调参。
输出 results/tables/alns_nopolish.csv"""
import os, sys, csv
sys.path.insert(0, os.path.dirname(__file__))
import run_alns as A, reprice as RP
import inst_config as CFG

TBL = os.path.join(CFG.ROOT, "results", "tables")
OUT = os.path.join(TBL, "alns_nopolish.csv")

rows = []
for tag in ["S", "M", "L", "X", "XL"]:
    inst = A.gen_inst(tag)
    stime = CFG.SA_TIME.get(tag, 180)
    ft, lr, hc, hm, wt = A.solve_alns(inst, time_limit=stime, seed=42,
                                      max_iters=None, use_polish=False)
    rc, st = RP.reprice(inst, ft, lr)
    with open(os.path.join(TBL, "mixfleet_bench.csv"), encoding="utf-8-sig") as fh:
        mx = next(r for r in csv.DictReader(fh) if r["instance"].startswith(tag + ":"))
    gap = 100.0 * (rc - float(mx["cpx_cost"])) / float(mx["cpx_cost"])
    rows.append(dict(instance=tag, alns_nopolish_reprice=f"{rc:.0f}", status=st,
                     time_s=f"{wt:.0f}", iters=hm["iters"], budget_s=stime,
                     cpx_incumbent=mx["cpx_cost"], gap_inc_pct=f"{gap:.2f}"))
    print(f"{tag}: no-polish reprice {rc:.0f} gap {gap:.2f}% ({hm['iters']} it, {wt:.0f}s)", flush=True)
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
print("saved ->", OUT, flush=True)
