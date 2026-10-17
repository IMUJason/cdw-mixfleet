# -*- coding: utf-8 -*-
"""LP 松弛 gap 对比(紧致 MTZ-only vs 吨位流强化) + MTZ 冗余性验证。
C1: 每实例两种公式的根 LP 松弛: 全变量连续化后解 LP, gap_LP = (incumbent-LP)/incumbent。
C4: 强化公式去 MTZ 的完整 MIP(S/M, 与 bench 同限) —— 吨位流平衡已兼任连通性, 验证冗余。
输出 results/tables/lp_gaps.csv 与 results/tables/mtz_redundancy.csv。"""
import os, sys, csv, time
sys.path.insert(0, os.path.dirname(__file__))
import pulp
import params as P, mixfleet_model as MF, inst_config as CFG

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TBL = os.path.join(ROOT, "results", "tables")
CASES = {"S": 42, "M": 42, "L": 42, "X": 42, "XL": 7}
CPLEX_LIMIT = {"S": 300, "M": 900, "L": 1200, "X": 1800, "XL": 1800}
LP_CAP = 900          # 单个 LP 松弛求解上限


def gen(tag, seed):
    if tag == "XL":
        import run_xl
        return run_xl.gen_xl()
    return CFG.gen(tag, seed)


def lp_relax(inst, use_flow, use_mtz=True):
    """建 MIP(solve=False) → 全变量连续化 → 解 LP → (目标值, 墙钟, 状态)。"""
    m, _ = MF.build_mip(inst, solve=False, use_flow=use_flow, use_mtz=use_mtz)
    for v in m.variables():
        v.cat = pulp.LpContinuous
    t0 = time.time()
    m.solve(P.get_solver(msg=0, timeLimit=LP_CAP))
    wt = time.time() - t0
    obj = pulp.value(m.objective) if m.status == pulp.LpStatusOptimal else None
    return obj, wt, pulp.LpStatus[m.status]


def main():
    bench = {}
    with open(os.path.join(TBL, "mixfleet_bench.csv"), encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            bench[r["instance"].split(":")[0]] = r

    rows = []
    for tag, seed in CASES.items():
        inst = gen(tag, seed)
        inc = float(bench[tag]["cpx_cost"])
        for name, flow in [("compact", False), ("strengthened", True)]:
            print(f"[{tag}] LP {name} ...", flush=True)
            obj, wt, st = lp_relax(inst, flow)
            if obj is None:
                print(f"[{tag}] {name}: {st} (LP 失败/超时)", flush=True)
                continue
            gap = (inc - obj) / inc * 100.0
            rows.append({"instance": tag, "formulation": name,
                         "lp_obj": f"{obj:.1f}", "lp_time_s": f"{wt:.0f}", "lp_status": st,
                         "incumbent": f"{inc:.0f}", "lp_gap_pct": f"{gap:.1f}"})
            print(f"[{tag}] {name}: LP {obj:.1f} ({wt:.0f}s) gap {gap:.1f}%", flush=True)
    with open(os.path.join(TBL, "lp_gaps.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print("wrote lp_gaps.csv", flush=True)

    # ---- C4: 强化公式去 MTZ, 完整 MIP, S/M 两实例(与 bench 同限同容差) ----
    rows2 = []
    for tag in ["S", "M"]:
        inst = gen(tag, CASES[tag])
        lim = CPLEX_LIMIT[tag]
        print(f"[{tag}] MIP no-MTZ ({lim}s cap) ...", flush=True)
        t0 = time.time()
        m, _ = MF.build_mip(inst, time_limit=lim, gap=1e-3, use_flow=True, use_mtz=False)
        wt = time.time() - t0
        rep = MF.solver_report(m)
        b = bench[tag]
        rows2.append({"instance": tag, "no_mtz_status": rep["status"],
                      "no_mtz_incumbent": f"{rep['incumbent']:.0f}" if rep["incumbent"] else "",
                      "no_mtz_bound": f"{rep['bound']:.0f}" if rep["bound"] is not None else "",
                      "no_mtz_time_s": f"{wt:.0f}",
                      "bench_incumbent": b["cpx_cost"], "bench_bound": b["cpx_bound"],
                      "bench_time_s": b["cpx_time"]})
        print(f"[{tag}] no-MTZ: {rep['status']} inc {rep['incumbent']:.0f} "
              f"bound {rep['bound']:.0f} ({wt:.0f}s) | bench {b['cpx_cost']}/{b['cpx_bound']}"
              f" ({b['cpx_time']}s)", flush=True)
    with open(os.path.join(TBL, "mtz_redundancy.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows2[0].keys()))
        w.writeheader(); w.writerows(rows2)
    print("wrote mtz_redundancy.csv", flush=True)


if __name__ == "__main__":
    main()
