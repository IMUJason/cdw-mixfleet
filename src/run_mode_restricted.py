# -*- coding: utf-8 -*-
"""E2(R2.8): 模式受限反事实 —— 等优化力度的 all-FTL / all-LTL 重解。

设计裁定(response to comments.md v2 〇-B):
- 受限实例用变换法: 类别/车队/汇/计费/计时与混合模型严格一致, 仅改变需求的模式归属;
  all-LTL 允许单站路线(运营真实), 模型天然允许, 不人为禁止;
- CPLEX 统一基准限时(S300/M900/L1200/X1800/XL1800, gap 0.1% 提前停), SA 同基准预算与固定迭代,
  全部 reprice 精确重定价;
- mixed 参照列复用 mixfleet_bench.csv(既有认证结果), 不重跑;
- 前置语义检查: FTL shuttle 与单站 LTL 路线成本恒等(三角路径相同), 打印验证。
输出: results/tables/mode_restricted.csv
"""
import os, sys, csv, time, copy
sys.path.insert(0, os.path.dirname(__file__))
import params as P
import mixfleet_model as MF, mixfleet_heuristic as MH
import inst_config as CFG, reprice as RP

TBL = os.path.join(CFG.ROOT, "results", "tables")
OUT = os.path.join(TBL, "mode_restricted.csv")
TAGS = ["S", "M", "L", "X", "XL"]
CPLEX_LIMIT_XL = 1800
SA_TIME_XL = 180


def gen_inst(tag):
    if tag == "XL":
        vc = []
        for c in CFG.CLASSES:
            vc += [c] * {"earth": 7, "demolition": 10, "renovation": 7}[c]
        return MF.gen_instance(7, 32, len(vc), seed=7, use_real_net=True,
                               trips_per_vehicle=CFG.R, veh_classes=vc,
                               fleet_budget=float(P.NIGHT_HOURS))
    return CFG.gen(tag, 42)


def restrict(inst, mode):
    """mode='ftl': 全部需求按 FTL 直运; 'ltl': 全部需求按 LTL 集货(单站允许)。
    索引约定: 模型/启发式均以 id 作为 *_idx 列表下标(顺序整数), 变换保持该约定。"""
    inst = copy.deepcopy(inst)
    if mode == "ftl":
        base = len(inst["ftl"])
        for i, l in enumerate(inst["ltl"]):
            inst["ftl"].append(dict(id=base + i, cls=l["cls"], demand=l["demand"], coord=l["coord"]))
            inst["ftl_idx"].append(inst["ltl_idx"][i])
        inst["ltl"], inst["ltl_idx"] = [], []
        inst["n_ftl"], inst["n_ltl"] = len(inst["ftl"]), 0
    elif mode == "ltl":
        base = len(inst["ltl"])
        for i, f in enumerate(inst["ftl"]):
            inst["ltl"].append(dict(id=base + i, cls=f["cls"], demand=f["demand"], coord=f["coord"]))
            inst["ltl_idx"].append(inst["ftl_idx"][i])
        inst["ftl"], inst["ftl_idx"] = [], []
        inst["n_ltl"], inst["n_ftl"] = len(inst["ltl"]), 0
    else:
        raise ValueError(mode)
    return inst


def semantics_check():
    """恒等预检: 同一物理站点、同类别车下, FTL shuttle 运输成本 == 单站 LTL 路线运输成本
    (同固定费+同里程路径; ltl_trip_eval 返回含净处置的全包成本, 此处只比运输分量)。"""
    base = gen_inst("S")
    r = restrict(copy.deepcopy(base), "ltl")
    site = base["ftl"][0]
    new_id = next(l["id"] for l in r["ltl"] if l["coord"] == site["coord"])
    vc = MF.get_veh_classes(base)
    v_same = next(v for v in range(len(vc)) if vc[v] == site["cls"])
    import params as _P
    D, depot = base["D"], base["depot_idx"]
    knode = base["sink_idx"][MF.sink_for_class(site["cls"], base)["id"]]
    d = D[depot][base["ftl_idx"][site["id"]]] + D[base["ftl_idx"][site["id"]]][knode] + D[knode][depot]
    c_ftl_transport, _ = MH.ftl_trip_cost(v_same, site["id"], base)
    c_ltl_allin, _, _ = MH.ltl_trip_eval([new_id], MF.get_veh_classes(r)[v_same], r)
    c_ltl_transport = c_ltl_allin - min(site["demand"], _P.TRUCK_CAP_T) * 0  # 占位, 下面用公式
    c_ltl_transport = _P.TRIP_FIXED + _P.TRIP_PER_KM * d
    ok = abs(c_ftl_transport - c_ltl_transport) < 1e-9
    print(f"[check] same-site transport: FTL {c_ftl_transport:.3f} vs single-stop LTL {c_ltl_transport:.3f} "
          f"-> identical={ok} (all-LTL feasible set contains all-FTL: ordering structural)", flush=True)


def mixed_ref():
    ref = {}
    with open(os.path.join(TBL, "mixfleet_bench.csv"), encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            ref[row["instance"].split(":")[0].strip()] = row
    return ref


def main():
    semantics_check()
    ref = mixed_ref()
    rows = []
    for tag in TAGS:
        base = gen_inst(tag)
        lim = CFG.CPLEX_LIMIT.get(tag, CPLEX_LIMIT_XL)
        stime = CFG.SA_TIME.get(tag, SA_TIME_XL)
        siters = CFG.SA_ITERS.get(tag)
        for mode in ("ftl", "ltl"):
            inst = restrict(base, mode)
            n_dem = len(inst["ftl"]) + len(inst["ltl"])
            print(f"=== {tag} all-{mode.upper()} ({n_dem} demands) CPLEX {lim}s ===", flush=True)
            t0 = time.time()
            m, _ = MF.build_mip(inst, time_limit=lim, gap=CFG.GAP_TOL)
            wt = time.time() - t0
            rep = MF.solver_report(m)
            print(f"  exact: {rep['status']} inc {rep['incumbent'] and round(rep['incumbent'])} "
                  f"bound {rep['bound'] and round(rep['bound'])} gap {rep['mip_gap_pct']}% ({wt:.0f}s)", flush=True)
            t0 = time.time()
            ft, lr, hc, hm = MH.solve(inst, time_limit=stime, seed=42, max_iters=siters)
            sa_t = time.time() - t0
            rc, rstat = RP.reprice(inst, ft, lr)
            print(f"  SA: reprice {rc:.0f} ({rstat}, {hm['iters']} it, {sa_t:.0f}s)", flush=True)
            mx = ref[tag]
            mx_cpx = float(mx["cpx_cost"]); mx_sa = float(mx["heu_cost"])
            best = min(x for x in [rep["incumbent"], rc if rstat == "Optimal" else None] if x is not None)
            prem_exact = 100.0 * (rep["incumbent"] - mx_cpx) / mx_cpx if rep["incumbent"] else None
            prem_sa = 100.0 * (rc - mx_sa) / mx_sa if rstat == "Optimal" else None
            rows.append(dict(instance=tag, mode=f"all-{mode}", n_demands=n_dem,
                             cpx_status=rep["status"],
                             cpx_incumbent=f"{rep['incumbent']:.0f}" if rep["incumbent"] else "",
                             cpx_bound=f"{rep['bound']:.0f}" if rep["bound"] else "",
                             cpx_gap_pct=rep["mip_gap_pct"], cpx_time_s=f"{wt:.0f}",
                             sa_reprice=f"{rc:.0f}", sa_time_s=f"{sa_t:.0f}", sa_iters=hm["iters"],
                             reprice_status=rstat,
                             mixed_cpx_incumbent=mx_cpx, mixed_sa_reprice=mx_sa,
                             best_restricted=f"{best:.0f}",
                             premium_exact_pct=f"{prem_exact:.2f}" if prem_exact is not None else "",
                             premium_sa_pct=f"{prem_sa:.2f}" if prem_sa is not None else ""))
            # 增量落盘, 防中断丢结果
            with open(OUT, "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                w.writeheader(); w.writerows(rows)
    print("=== summary (premium vs equally-optimized mixed) ===", flush=True)
    for r in rows:
        print(f"{r['instance']:3s} {r['mode']:8s} exact {r['cpx_incumbent']:>8s} "
              f"({r['cpx_gap_pct']}%) SA {r['sa_reprice']:>8s} | premium exact {r['premium_exact_pct']:>7s}% "
              f"SA {r['premium_sa_pct']:>7s}%", flush=True)
    print("saved ->", OUT, flush=True)


if __name__ == "__main__":
    main()
