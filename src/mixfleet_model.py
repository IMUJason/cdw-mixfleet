"""CDW-MixFleet: 有限车队下的 大宗整车(FTL) + 小宗集货(LTL) 混合调度。
现实: 土方/拆除大宗=整车直运(FTL); 装修/小宗=零担集货(LTL, 车辆穿越多站拼载后经中转分选)。
决策者: 承运商有限类别专营车队, 在 FTL/LTL 模式间分配车辆与时间, 夜间窗, 处置点容量, 资源化政策。
难在: LTL 集货穿越(TSP 序) × FTL/LTL 模式分配 × 有限车队耦合 → CPLEX 难解, 启发式有戏。
求解: CPLEX 精确(小规模) vs ALNS 元启发式(大规模)。结果真实跑出。"""
import os, math, json
import numpy as np
import pulp
import params as P


def haversine_km(a, b, c, d):
    R = 6371.0; p1, p2 = math.radians(b), math.radians(d)
    dp, dl = math.radians(d - b), math.radians(c - a)
    aa = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(aa))


def gen_instance(n_ftl=6, n_ltl=16, n_vehicles=8, seed=42, use_real_net=True, trips_per_vehicle=5,
                 veh_classes=None, fleet_budget=None):
    """veh_classes: 显式每车类别列表(默认 v%%3 轮转); fleet_budget: 每车总时间预算(默认 H%%trips)。"""
    """FTL 点(大宗, 整车直运) + LTL 站点(小宗, 集货穿越)。真实路网坐标。"""
    rng = np.random.default_rng(seed)
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    net_path = os.path.join(ROOT, "data", "external", "dongsheng_real_network.json")
    if use_real_net and os.path.exists(net_path):
        net = json.load(open(net_path, encoding="utf-8"))
        depot_coord = tuple(float(x) for x in net["facilities"][0]["loc"].split(","))
        gz = [tuple(float(x) for x in g["loc"].split(",")) for g in net["gen_zones"]]
        def coord(i, s=0.02): return (round(gz[i % len(gz)][0]+float(rng.normal(0, s)), 6),
                                      round(gz[i % len(gz)][1]+float(rng.normal(0, s)), 6))
        depot = dict(loc=depot_coord, name=net["facilities"][0].get("name"))
    else:
        depot = dict(loc=(110.07, 39.89), name="depot")
        def coord(i, s=0.15): return (round(109.95+rng.uniform(0, s), 6), round(39.80+rng.uniform(0, 0.12), 6))
    # FTL 点: 大宗(土方/拆除), 整车
    ftl = []
    for i in range(n_ftl):
        cls = str(rng.choice(["earth", "demolition"]))
        dem = float(np.clip(rng.lognormal(math.log(150.0), 0.7), 40.0, 600.0))  # 大宗
        ftl.append(dict(id=i, cls=cls, demand=round(dem, 1), coord=coord(i)))
    # LTL 站点: 小宗(装修/拆除混合), 集货穿越
    ltl = []
    for i in range(n_ltl):
        cls = str(rng.choice(["renovation", "demolition"]))
        dem = float(np.clip(rng.lognormal(math.log(18.0), 0.7), 5.0, 45.0))  # 小宗
        ltl.append(dict(id=i, cls=cls, demand=round(dem, 1), coord=coord(n_ftl + i)))
    # 汇: backfill(土方) / resource(拆除/装修经分选) / landfill
    sinks = [
        dict(id=0, type="backfill", fee=P.SINK_FEE["backfill"], revenue=P.SINK_REVENUE["backfill"],
             coord=(109.80, 39.84), cap=1e9, note="synthetic: placed at Hantai-Town western outskirts (real backfill sites not published as POIs; driving distances proxied by the Hantai-Town anchor row)"),
        dict(id=1, type="resource", fee=P.SINK_FEE["resource"], revenue=P.SINK_REVENUE["resource"], coord=(110.08, 39.89), cap=1e9),
        dict(id=2, type="landfill", fee=P.SINK_FEE["landfill"], revenue=0.0, coord=(109.96, 39.92), cap=1e9),
    ]
    allcoords = [depot["loc"]] + [f["coord"] for f in ftl] + [l["coord"] for l in ltl] + [k["coord"] for k in sinks]
    nn = len(allcoords)
    if use_real_net and os.path.exists(net_path):
        # 真实驾车距离: 站点→锚点 直线接入段 + 锚点间 高德驾车矩阵(API 实测)
        net_nodes = net["nodes"]; mat = net["matrix"]
        def _loc(s):
            a, b = s.split(","); return float(a), float(b)
        anchors = [int(np.argmin([haversine_km(c[0], c[1], *_loc(n["loc"])) for n in net_nodes])) for c in allcoords]
        access = [haversine_km(c[0], c[1], *_loc(net_nodes[a]["loc"])) for c, a in zip(allcoords, anchors)]
        def dreal(i, j):
            if i == j: return 0.0
            cell = mat[anchors[i]][anchors[j]]
            drv = cell["dist_km"] if cell else 1.30 * haversine_km(allcoords[i][0], allcoords[i][1], allcoords[j][0], allcoords[j][1])
            return round(access[i] + drv + access[j], 3)
        D = [[dreal(i, j) for j in range(nn)] for i in range(nn)]
    else:
        D = [[round(haversine_km(allcoords[i][0], allcoords[i][1], allcoords[j][0], allcoords[j][1]), 3) for j in range(nn)] for i in range(nn)]
    if veh_classes is not None:
        assert len(veh_classes) == n_vehicles and all(c in P.CLASSES for c in veh_classes)
    return dict(n_ftl=n_ftl, n_ltl=n_ltl, n_vehicles=n_vehicles, seed=seed, depot=depot, ftl=ftl, ltl=ltl,
                veh_classes=list(veh_classes) if veh_classes else None,
                fleet_budget=fleet_budget,
                sinks=sinks, D=D, depot_idx=0, ftl_idx=list(range(1, 1+n_ftl)),
                ltl_idx=list(range(1+n_ftl, 1+n_ftl+n_ltl)), sink_idx=list(range(1+n_ftl+n_ltl, nn)),
                real=use_real_net, trips_per_vehicle=trips_per_vehicle)


def get_veh_classes(inst):
    """每车类别: 显式 inst['veh_classes'] 优先, 否则 v%%3 轮转(旧行为)。"""
    vc = inst.get("veh_classes")
    if vc:
        return list(vc)
    return [P.CLASSES[v % 3] for v in range(inst["n_vehicles"])]


def sink_for_class(cls, inst):
    for k in inst["sinks"]:
        if cls == "earth" and k["type"] == "backfill": return k
        if cls in ("demolition", "renovation") and k["type"] == "resource": return k
    return inst["sinks"][-1]


def build_mip(inst, time_limit=1800, gap=0.02, fleet_budget=None, solve=True,
              use_flow=True, use_mtz=True):
    """CDW-MixFleet MILP(NP-hard):
    FTL: 整车直运(指派整数趟); LTL: 集货穿越(TSP 序 MTZ 消环, 部分装载≤W)。
    有限车队(类别专营), 趟时间≤夜间窗。CPLEX 1800s 难求最优 → 启发式有戏。
    fleet_budget: 每车总时间预算; 默认 NIGHT*ntr(多夜口径), 单夜探测时传 NIGHT。
    solve=False 时仅建模型不求解(供 reprice.py 固定结构后重定价)。
    use_flow=False: 紧致对照公式(去吨位流强化, LP 松弛对比实验用);
    use_mtz=False: 去 MTZ(吨位流平衡已兼任连通性, 冗余性验证实验用)。
    默认 True/True 与历史行为逐位一致。"""
    ftl = inst["ftl"]; ltl = inst["ltl"]; D = inst["D"]; depot = inst["depot_idx"]
    V = range(inst["n_vehicles"]); W = P.TRUCK_CAP_T; NIGHT = P.NIGHT_HOURS; ntr = inst.get("trips_per_vehicle", 5)
    node_of_ftl = {f["id"]: inst["ftl_idx"][f["id"]] for f in ftl}
    node_of_ltl = {l["id"]: inst["ltl_idx"][l["id"]] for l in ltl}
    node_of_sink = {k["id"]: inst["sink_idx"][k["id"]] for k in inst["sinks"]}
    fcls = {f["id"]: f["cls"] for f in ftl}; lcls = {l["id"]: l["cls"] for l in ltl}
    veh_cls = get_veh_classes(inst)
    m = pulp.LpProblem("CDW_MixFleet", pulp.LpMinimize)
    # ---- FTL 变量: ntrip_ftl[v,f] 整数趟(直运) + 实载量 s(允许最后一趟半载) ----
    ntr_f = {}; served_f = {}
    for v in V:
        vc = veh_cls[v]
        for f in ftl:
            if fcls[f["id"]] == vc:
                ntr_f[v, f["id"]] = pulp.LpVariable(f"nf_{v}_{f['id']}", lowBound=0, cat="Integer")
    for f in ftl:
        served_f[f["id"]] = pulp.LpVariable(f"sf_量_{f['id']}", lowBound=0, upBound=f["demand"])
    # ---- LTL 变量: 穿越弧 z[v,t,i,j], MTZ u, 装载 load, 吨位流 f ----
    z = {}; u = {}; load = {}; un_ltl = {}; short_ftl = {}; fflow = {}
    for l in ltl:
        un_ltl[l["id"]] = pulp.LpVariable(f"unl_{l['id']}", lowBound=0, upBound=l["demand"])
    for f in ftl:
        short_ftl[f["id"]] = pulp.LpVariable(f"sf_{f['id']}", lowBound=0, upBound=f["demand"])
    for v in V:
        vc = veh_cls[v]
        k_v = sink_for_class(vc, inst); knode_v = node_of_sink[k_v["id"]]
        lsvc = [l["id"] for l in ltl if lcls[l["id"]] == vc]
        for t in range(ntr):
            for l in lsvc:
                load[v, t, l] = pulp.LpVariable(f"ld_{v}_{t}_{l}", lowBound=0, upBound=W)
                if use_mtz:
                    u[v, t, l] = pulp.LpVariable(f"u_{v}_{t}_{l}", lowBound=1, upBound=len(lsvc) + 1)
            # 路线网络: depot → 站点(TSP) → 汇 → depot (汇=终节点)
            nodes_v = [depot] + [node_of_ltl[l] for l in lsvc] + [knode_v]
            for i in nodes_v:
                for j in nodes_v:
                    if i != j:
                        # 汇→站点 不允许(汇是终点); depot→汇 不允许(空趟)
                        if j == knode_v and i == knode_v: continue
                        if i == knode_v and j != depot: continue  # 汇只能回 depot
                        if i == depot and j == knode_v: continue  # depot 不直去汇
                        z[v, t, i, j] = pulp.LpVariable(f"z_{v}_{t}_{i}_{j}", cat="Binary")
                        # 吨位流: 弧 (i,j) 上的已装吨位; depot 出弧空载(f=0)不创建, 汇返回弧空载不创建
                        if use_flow and i != depot and i != knode_v:
                            fflow[v, t, i, j] = pulp.LpVariable(f"ff_{v}_{t}_{i}_{j}", lowBound=0, upBound=W)
    # ---- 目标(承运商视角: 按车次计费 + 车队固定 + 按吨位处置/收益) ----
    transport = 0; disposal = 0; revenue = 0
    # FTL: 每趟 = 固定出车 + 里程价×往返距离; 处置/收益按【实载吨位】(最后一趟可半载)
    for (v, fid), var in ntr_f.items():
        f = next(x for x in ftl if x["id"] == fid)
        d_ftl = D[depot][node_of_ftl[fid]]
        k = sink_for_class(fcls[fid], inst); knode = node_of_sink[k["id"]]
        d = d_ftl + D[node_of_ftl[fid]][knode] + D[knode][depot]
        transport += var * (P.TRIP_FIXED + P.TRIP_PER_KM * d)          # 车次成本(固定+里程)
    for f in ftl:
        k = sink_for_class(fcls[f["id"]], inst)
        disposal += served_f[f["id"]] * k["fee"]; revenue += served_f[f["id"]] * k["revenue"]  # 按实载吨位
    # LTL: 弧里程价 + depot出发弧=趟固定; 处置/收益按实际装载吨位
    for v in V:
        vc = veh_cls[v]; k = sink_for_class(vc, inst)
        for t in range(ntr):
            for (vv, tt, i, j), var in z.items():
                if vv == v and tt == t:
                    transport += var * D[i][j] * P.TRIP_PER_KM         # 里程价(按实际弧距离)
                    if i == depot:
                        transport += var * P.TRIP_FIXED                 # depot出发=趟启用, 加固定
            for l in [x["id"] for x in ltl if lcls[x["id"]] == vc]:
                if (v, t, l) in load:
                    disposal += load[v, t, l] * k["fee"]; revenue += load[v, t, l] * k["revenue"]  # 按实际吨位
    short_pen = pulp.lpSum([un_ltl[l["id"]] * P.SHORTAGE_PENALTY for l in ltl]) + \
                pulp.lpSum([short_ftl[f["id"]] * P.SHORTAGE_PENALTY for f in ftl])
    m += transport + disposal + short_pen - revenue
    # ---- 约束 ----
    # FTL 需求: 实载 ≤ 需求, 实载 ≤ 趟数×W(半载合法); short = demand - served
    for f in ftl:
        fid = f["id"]
        trip_cap = pulp.lpSum([ntr_f[v, fid] * W for (v, ff) in ntr_f if ff == fid])
        m += served_f[fid] <= trip_cap, f"fcap_{fid}"
        m += short_ftl[fid] == f["demand"] - served_f[fid], f"fdem_{fid}"
    # LTL 需求
    for l in ltl:
        lid = l["id"]
        m += un_ltl[lid] == l["demand"] - pulp.lpSum([load[v, t, lid] for (v, t, ss) in load if ss == lid]), f"ldem_{lid}"
    # 每车: FTL 趟 + LTL 趟 时间窗耦合(有限车队核心)
    for v in V:
        vc = veh_cls[v]; k = sink_for_class(vc, inst); knode = node_of_sink[k["id"]]
        lsvc = [l["id"] for l in ltl if lcls[l["id"]] == vc]
        nodes_v = [depot] + [node_of_ltl[l] for l in lsvc] + [knode]  # 含汇
        # FTL 趟时间
        ftl_time = pulp.lpSum([ntr_f[v, f["id"]] * ((D[depot][node_of_ftl[f["id"]]] + D[node_of_ftl[f["id"]]][knode] + D[knode][depot]) / 35.0 + P.FTL_SVC_H)
                               for f in ftl if (v, f["id"]) in ntr_f]) if any((v, f["id"]) in ntr_f for f in ftl) else 0
        for t in range(ntr):
            # LTL 趟: 装载≤W, 穿越+装卸 ≤ 夜间窗(与 FTL 共享车队时间)
            lds = [load[v, t, l] for l in lsvc if (v, t, l) in load]
            if lds: m += pulp.lpSum(lds) <= W, f"lcap_{v}_{t}"
            for l in lsvc:
                node = node_of_ltl[l]
                inf = pulp.lpSum([z[v, t, i, node] for i in nodes_v if (v, t, i, node) in z and i != node])
                outf = pulp.lpSum([z[v, t, node, j] for j in nodes_v if (v, t, node, j) in z and j != node])
                m += inf == outf, f"lbal_{v}_{t}_{l}"
                m += inf <= 1, f"lonce_{v}_{t}_{l}"
                if (v, t, l) in load:
                    m += load[v, t, l] <= W * inf, f"lvis_{v}_{t}_{l}"
            # 汇: 若趟启用(有 depot 出弧), 必经汇回 depot
            depot_out = pulp.lpSum([z[v, t, depot, j] for j in nodes_v if (v, t, depot, j) in z])
            sink_in = pulp.lpSum([z[v, t, i, knode] for i in nodes_v if (v, t, i, knode) in z and i != knode])
            sink_out = pulp.lpSum([z[v, t, knode, j] for j in nodes_v if (v, t, knode, j) in z and j != knode])
            m += sink_in == depot_out, f"sk_in_{v}_{t}"
            m += sink_out == depot_out, f"sk_out_{v}_{t}"
            for i in lsvc:
                for j in lsvc:
                    if use_mtz and i != j and (v, t, node_of_ltl[i], node_of_ltl[j]) in z:
                        m += u[v, t, i] - u[v, t, j] + (len(lsvc)+1) * z[v, t, node_of_ltl[i], node_of_ltl[j]] <= len(lsvc), \
                           f"lmtz_{v}_{t}_{i}_{j}"
            # ---- 吨位流(单商品流)强耦合: 分数弧必须携带一致的吨位流 ----
            # 1) 流上界 = 容量×弧访问
            if use_flow:
                for key, var in list(fflow.items()):
                    (vv, tt, i, j) = key
                    if vv == v and tt == t:
                        m += var <= W * z[v, t, i, j], f"ffcap_{v}_{t}_{i}_{j}"
                # 站点流平衡: 净流出 = 装载量(装货使车上吨位增加)
                for l in lsvc:
                    node = node_of_ltl[l]
                    outf = pulp.lpSum([fflow[v, t, node, j] for j in nodes_v if (v, t, node, j) in fflow])
                    inf = pulp.lpSum([fflow[v, t, i, node] for i in nodes_v if (v, t, i, node) in fflow])
                    if (v, t, l) in load:
                        m += outf - inf == load[v, t, l], f"ffbal_{v}_{t}_{l}"
                # 汇入流 = 总装载(卸光); depot 出弧空载已由变量缺失隐式保证
                total_load = pulp.lpSum([load[v, t, l] for l in lsvc if (v, t, l) in load])
                sink_in_flow = pulp.lpSum([fflow[v, t, i, knode] for i in nodes_v
                                           if (v, t, i, knode) in fflow])
                m += sink_in_flow == total_load, f"ffsink_{v}_{t}"
            tt = pulp.lpSum([var * D[i][j] / 35.0 for (veh, tslot, i, j), var in z.items() if veh == v and tslot == t]) + \
                 pulp.lpSum([load[v, t, l] for l in lsvc if (v, t, l) in load]) / W * P.LOAD_UNLOAD_H + \
                 P.LTL_STOP_H * pulp.lpSum([var for (veh, tslot, i, j), var in z.items()
                                            if veh == v and tslot == t and j in [node_of_ltl[l] for l in lsvc]])
            m += tt <= NIGHT, f"ltw_{v}_{t}"
        # FTL+LTL 共享车队总时间(有限车队耦合; 装卸时间计入, 与 per-trip 窗口及论文 eq(8) 一致)
        # 注意: 用 items() 遍历, 引用解包键的 tt, 避免外层循环陈旧变量(历史 bug 教训)
        ltl_total = pulp.lpSum([var * D[i][j] / 35.0 for (veh, tt, i, j), var in z.items() if veh == v]) + \
                    pulp.lpSum([var for (veh, tt, l), var in load.items() if veh == v]) / W * P.LOAD_UNLOAD_H + \
                    P.LTL_STOP_H * pulp.lpSum([var for (veh, tt, i, j), var in z.items()
                                               if veh == v and j in [node_of_ltl[l] for l in lsvc]])
        fb = inst.get("fleet_budget")
        budget_v = next((x for x in (fleet_budget, fb) if x is not None), NIGHT * ntr)
        m += ftl_time + ltl_total <= budget_v, f"fleet_{v}"
    if solve:
        m.solve(P.get_solver(msg=0, timeLimit=time_limit, gapRel=gap))
    return m, dict(ntr_f=ntr_f, z=z, load=load, un_ltl=un_ltl, short_ftl=short_ftl)


def solver_report(m):
    """读取求解结果与认证信息: 状态/incumbent/best-bound/最终 MIP gap。
    get_best_objective() 返回对偶界(min 问题 ≤ incumbent); CBC 无此接口时 bound=None。"""
    rep = dict(status=pulp.LpStatus[m.status],
               incumbent=pulp.value(m.objective) if m.status in (1,) else None,
               bound=None, mip_gap_pct=None)
    sm = getattr(m, "solverModel", None)
    if sm is not None and hasattr(sm, "solution"):
        try:
            s = sm.solution
            rep["incumbent"] = s.get_objective_value()
            rep["bound"] = s.MIP.get_best_objective()
            rep["mip_gap_pct"] = round(s.MIP.get_mip_relative_gap() * 100.0, 4)
        except Exception:
            pass
    return rep


if __name__ == "__main__":
    import time
    for nf, nl, nv in [(4, 12, 8), (6, 20, 12), (8, 30, 16)]:
        inst = gen_instance(nf, nl, nv, seed=42, use_real_net=True, trips_per_vehicle=5)
        t0 = time.time(); m, vv = build_mip(inst, time_limit=1800, gap=0.03); ct = time.time() - t0
        print(f"FTL{nf}+LTL{nl}/{nv}veh: CPLEX status={pulp.LpStatus[m.status]} cost={pulp.value(m.objective)/1e6 if m.status in (1,) else float('nan'):.4f}M time={ct:.0f}s", flush=True)
