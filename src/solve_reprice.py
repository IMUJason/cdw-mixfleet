#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""方案精确重定价(独立复核): python solve_reprice.py instances/S.csv out/S_sa_plan.csv
结构(FTL 趟数 + LTL 穿越序列)固定, 载荷 LP 自由优化 —— 论文所有 SA 成本的报告口径。"""
import os, sys, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plan_io as PIO
import reprice as RP
from instance_io import load_instance


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance")
    ap.add_argument("plan")
    a = ap.parse_args()
    inst = load_instance(a.instance)
    meta, ftl, ltl = PIO.load_plan(a.plan)
    rc, st = RP.reprice(inst, ftl, ltl)
    if rc is None:
        print(f"plan infeasible under exact model ({st})")
        sys.exit(1)
    print(f"exact re-priced cost = {rc:.2f} ({st}); "
          f"plan file reports reported_cost={meta.get('reported_cost', meta.get('cost', 'NA'))}")


if __name__ == "__main__":
    main()
