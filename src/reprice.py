# -*- coding: utf-8 -*-
"""计划精确重定价: 给定 (FTL 趟数指派, LTL 每车穿越序列) 的 dispatch 计划,
在 MIP 中固定其弧结构/趟数, 放开载荷 (s_f, y^{vt}_l) 由 CPLEX 重优化 —— 得到该结构
在精确公式下的最优成本。用于所有论文报告口径: SA/反事实/敏感性 的 heu 列一律用此
精确成本, 避免 evaluate() 贪心装载(先到先装)与 MIP 自由载荷分配之间的口径偏差
(贪心分配会系统性多计缺货, 曾使 CPLEX 最优计划重定价偏差 +30.6%)。
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import pulp
import params as P
import mixfleet_model as MF


def fix_plan(m, vv, inst, ftl_ntrip, ltl_routes):
    """把计划结构固定进模型: ntr_f 固定趟数; z 固定弧(z=0 的槽位整槽置 0)。"""
    ntr = inst.get("trips_per_vehicle", 5)
    # FTL 趟数固定
    for (v, fid), var in vv["ntr_f"].items():
        var.setInitialValue(float(ftl_ntrip.get((v, fid), 0)))
        var.fixValue()
    # LTL 弧固定: 每车把非空趟依次放入槽位 t=0,1,2,...
    z = vv["z"]; depot = inst["depot_idx"]
    veh_cls = MF.get_veh_classes(inst)
    for v in range(inst["n_vehicles"]):
        vc = veh_cls[v]
        k = MF.sink_for_class(vc, inst); knode = inst["sink_idx"][k["id"]]
        routes = [r for r in ltl_routes.get(v, []) if r]
        for t in range(ntr):
            chain = []
            if t < len(routes) and routes[t]:
                seq = [depot] + [inst["ltl_idx"][s] for s in routes[t]] + [knode, depot]
                chain = [(seq[i], seq[i + 1]) for i in range(len(seq) - 1)]
            for (vv, tt, i, j), var in z.items():
                if vv != v or tt != t:
                    continue
                var.setInitialValue(1.0 if (i, j) in chain else 0.0)
                var.fixValue()


def reprice(inst, ftl_ntrip, ltl_routes, msg=0):
    """返回 (cost, status): 计划在精确公式下的最优成本(结构固定, 载荷自由 LP)。
    计划不可行(载荷重优化后违反时间窗/预算)时返回 (None, status)。"""
    m, vv = MF.build_mip(inst, time_limit=60, gap=0.0, solve=False)
    fix_plan(m, vv, inst, ftl_ntrip, ltl_routes)
    m.solve(P.get_solver(msg=msg, timeLimit=60, gapRel=0.0))
    if m.status not in (pulp.LpStatusOptimal,):
        return None, pulp.LpStatus[m.status]
    return pulp.value(m.objective), pulp.LpStatus[m.status]


if __name__ == "__main__":
    import time
    import inst_config as CFG
    import mixfleet_heuristic as MH
    import verify_alignment as VA
    inst = CFG.gen("S", 42)
    t0 = time.time(); m, vv = MF.build_mip(inst, time_limit=300, gap=1e-3); ct = time.time() - t0
    rep = MF.solver_report(m)
    ftl_ntrip, ltl_routes, mrs = VA.extract_dispatch(m, vv, inst)
    rc, st = reprice(inst, ftl_ntrip, ltl_routes)
    ev = MH.evaluate(ftl_ntrip, ltl_routes, inst)
    print(f"CPLEX 最优计划: MIP={rep['incumbent']:.2f} evaluate={ev:.2f} reprice={rc:.2f} "
          f"({st})  重定价偏差={(rc - rep['incumbent']) / rep['incumbent'] * 100:+.4f}%")
    # SA 计划
    t0 = time.time(); ft, lr, hc, hm = MH.solve(inst, time_limit=30, seed=42); ht = time.time() - t0
    rc2, st2 = reprice(inst, ft, lr)
    print(f"SA 计划: evaluate={hc:.2f} reprice={rc2:.2f} ({st2})  差={(rc2 - hc):+.2f}")
