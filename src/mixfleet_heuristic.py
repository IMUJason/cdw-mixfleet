"""CDW-MixFleet 元启发式(SA/邻域): 目标与 mixfleet_model.MIP 严格一致。
先 tiny 对 CPLEX gap≈0 验证对齐, 再大规模(快+小gap)。
解: ftl_ntrip[(v,fid)]=整数趟(直运); ltl_routes[v]=[趟列表], 每趟=同类LTL站点穿越序列。
目标 = MIP 同式(运输 + 处置费 - 收益 + 缺货惩罚)。"""
import os, math, random, copy, time
import numpy as np
import params as P
import mixfleet_model as MF


# ---- 统一目标(镜像 MIP) ----
def ftl_trip_cost(v, fid, inst):
    """FTL 每趟运输成本(固定+里程)与时间。处置/收益按实载吨位在 evaluate 中计。"""
    vc = MF.get_veh_classes(inst)[v]
    k = MF.sink_for_class(vc, inst); knode = inst["sink_idx"][k["id"]]
    D = inst["D"]; depot = inst["depot_idx"]
    d = D[depot][inst["ftl_idx"][fid]] + D[inst["ftl_idx"][fid]][knode] + D[knode][depot]
    transport = P.TRIP_FIXED + P.TRIP_PER_KM * d
    return transport, d / 35.0


def ftl_tonnage(v, fid, ntrip, inst):
    """FTL 实载吨位: min(ntrip×W, 需求)。与 MIP served_f 一致。"""
    f = next(x for x in inst["ftl"] if x["id"] == fid)
    return min(ntrip * P.TRUCK_CAP_T, f["demand"])


def ltl_trip_eval(route, vc, inst):
    """LTL 一趟穿越: (含处置的全包成本, 实际装载, 时间)。
    注意: 处置/收益按该趟最大可能装载 min(Σ站点需求, W) 计 —— 仅用于邻域可行性预检与
    单趟参考成本; 整解定价必须用 evaluate() 的按实际分配口径(避免多趟分装重复计收益)。"""
    if not route: return 0.0, 0.0, 0.0
    D = inst["D"]; depot = inst["depot_idx"]
    k = MF.sink_for_class(vc, inst); knode = inst["sink_idx"][k["id"]]
    nodeseq = [depot] + [inst["ltl_idx"][l] for l in route] + [knode, depot]
    dist = sum(D[nodeseq[i]][nodeseq[i+1]] for i in range(len(nodeseq)-1))
    dem = {l["id"]: l["demand"] for l in inst["ltl"]}
    load = min(sum(dem[l] for l in route), P.TRUCK_CAP_T)
    time_h = dist / 35.0 + (load / P.TRUCK_CAP_T) * P.LOAD_UNLOAD_H   # 与 MIP ltw/fleet 约束同式
    transport = P.TRIP_FIXED + P.TRIP_PER_KM * dist       # 车次成本(固定+里程)
    disposal = load * k["fee"]; revenue = load * k["revenue"]
    return transport + disposal - revenue, load, time_h


def evaluate(ftl_ntrip, ltl_routes, inst):
    """整解成本 = FTL运输+处置-收益 + LTL运输 + LTL按实际分配吨位的处置-收益 + 缺货惩罚 + 超时/超趟惩罚。
    LTL 装载: 按 (车序, 趟序, 站序) 贪心分配, 每站累计 ≤ 需求, 每趟 ≤ W; 处置/收益只按实际
    装载吨位计(多趟分装不重复计收益 —— 与 MIP 的 y 变量口径一致)。"""
    veh_cls = MF.get_veh_classes(inst)
    ntr_max = inst.get("trips_per_vehicle", 5)
    total = 0.0
    ftl_served = {f["id"]: 0.0 for f in inst["ftl"]}
    ltl_served = {l["id"]: 0.0 for l in inst["ltl"]}
    # FTL: 运输按趟, 处置/收益按实载吨位(与 MIP served_f 一致)
    ftl_trips_per_veh = {}
    for (v, fid), ntrip in ftl_ntrip.items():
        if ntrip <= 0: continue
        c, th = ftl_trip_cost(v, fid, inst)
        total += c * ntrip
        ftl_trips_per_veh[v] = ftl_trips_per_veh.get(v, 0) + ntrip
    # 多车服务同一点时实载合并 ≤ demand
    for f in inst["ftl"]:
        fid = f["id"]
        trips_total = sum(n for (v, ff), n in ftl_ntrip.items() if ff == fid and n > 0)
        tons = min(trips_total * P.TRUCK_CAP_T, f["demand"])
        vc0 = None
        for (v, ff), n in ftl_ntrip.items():
            if ff == fid and n > 0: vc0 = veh_cls[v]; break
        if vc0 is not None:
            k = MF.sink_for_class(vc0, inst)
            total += tons * k["fee"] - tons * k["revenue"]
        ftl_served[fid] = tons
    # LTL: 运输按趟; 处置/收益按贪心实际装载(超时=硬违反, 天文惩罚)
    dem = {l["id"]: l["demand"] for l in inst["ltl"]}
    D = inst["D"]; depot = inst["depot_idx"]
    for v, trips in ltl_routes.items():
        vc = veh_cls[v]
        k = MF.sink_for_class(vc, inst); knode = inst["sink_idx"][k["id"]]
        for route in trips:
            if not route: continue
            nodeseq = [depot] + [inst["ltl_idx"][l] for l in route] + [knode, depot]
            dist = sum(D[nodeseq[i]][nodeseq[i+1]] for i in range(len(nodeseq)-1))
            total += P.TRIP_FIXED + P.TRIP_PER_KM * dist          # 纯运输(固定+里程)
            load = min(sum(dem[l] for l in route), P.TRUCK_CAP_T)
            time_h = dist / 35.0 + (load / P.TRUCK_CAP_T) * P.LOAD_UNLOAD_H
            if time_h > P.NIGHT_HOURS: total += 1e9 * (time_h - P.NIGHT_HOURS)   # 硬约束等效
            rem = P.TRUCK_CAP_T
            for l in route:
                take = min(dem[l] - ltl_served[l], rem)
                total += take * (k["fee"] - k["revenue"])          # 只按实际装载吨位计
                ltl_served[l] += take; rem -= take
    # 每车约束: LTL 趟数 ≤ trips_per_vehicle(变量空间); FTL+LTL 总时间 ≤ 每车预算(单夜=H)
    _fb = inst.get("fleet_budget")
    budget = _fb if _fb is not None else P.NIGHT_HOURS * ntr_max
    for v in range(inst["n_vehicles"]):
        ltl_count = len([t for t in ltl_routes.get(v, []) if t])
        if ltl_count > ntr_max:
            total += 10000.0 * (ltl_count - ntr_max)  # 超槽位重罚
        # 时间预算
        v_time = 0.0
        for (vv, fid), ntrip in ftl_ntrip.items():
            if vv == v and ntrip > 0:
                _, th = ftl_trip_cost(v, fid, inst)
                v_time += th * ntrip
        for route in ltl_routes.get(v, []):
            if route:
                _, _, th = ltl_trip_eval(route, veh_cls[v], inst)
                v_time += th
        if v_time > budget:
            total += 10000.0 * (v_time - budget)  # 超时重罚
    # 缺货惩罚
    for f in inst["ftl"]:
        total += max(0.0, f["demand"] - ftl_served[f["id"]]) * P.SHORTAGE_PENALTY
    for l in inst["ltl"]:
        total += max(0.0, l["demand"] - ltl_served[l["id"]]) * P.SHORTAGE_PENALTY
    return total


def construct(inst, rng):
    """构造: FTL 按需整车趟(轮转分车); LTL 每类最近邻打包穿越。每车趟数≤trips_per_vehicle。"""
    veh_cls = MF.get_veh_classes(inst)
    ntr_max = inst.get("trips_per_vehicle", 5)
    ftl_ntrip = {}
    dem = {l["id"]: l["demand"] for l in inst["ltl"]}
    veh_trips_left = {v: ntr_max for v in range(inst["n_vehicles"])}       # LTL 趟数槽
    _fb = inst.get("fleet_budget")
    budget = _fb if _fb is not None else P.NIGHT_HOURS * ntr_max
    veh_time_left = {v: budget for v in range(inst["n_vehicles"])}  # 每车总时间预算(FTL+LTL)
    # FTL: 轮转分配(按时间预算, 不限趟数 — 与 MIP 一致)
    cls_vehs = {c: [v for v in range(inst["n_vehicles"]) if veh_cls[v] == c] for c in P.CLASSES}
    for f in inst["ftl"]:
        fid = f["id"]; cls = f["cls"]
        need = math.ceil(f["demand"] / P.TRUCK_CAP_T)
        vs = cls_vehs.get(cls, [])
        # FTL 单趟时间
        k = MF.sink_for_class(cls, inst); knode = inst["sink_idx"][k["id"]]
        d = inst["D"][inst["depot_idx"]][inst["ftl_idx"][fid]] + inst["D"][inst["ftl_idx"][fid]][knode] + inst["D"][knode][inst["depot_idx"]]
        th = d / 35.0
        for _ in range(need):
            avail = [v for v in vs if veh_time_left.get(v, 0) >= th]
            if not avail: break
            v = avail[0]
            ftl_ntrip[(v, fid)] = ftl_ntrip.get((v, fid), 0) + 1
            veh_time_left[v] -= th
    # LTL: 每类最近邻打包(按剩余需求, 未装完的站可再访, 每车趟数受限)
    ltl_routes = {v: [] for v in range(inst["n_vehicles"])}
    for cls in P.CLASSES:
        rem_dem = {l["id"]: l["demand"] for l in inst["ltl"] if l["cls"] == cls}
        open_sites = [lid for lid, d in rem_dem.items() if d > 1e-3]
        vs = cls_vehs.get(cls, [])
        if not vs: continue
        guard = 0
        while open_sites and guard < 400:
            guard += 1
            # 找还有趟数和时间预算的车
            avail = [v for v in vs if veh_trips_left.get(v, 0) > 0 and veh_time_left.get(v, 0) > 1.0]
            if not avail: break
            v = avail[0]; veh_trips_left[v] -= 1
            route = []; cap_left = P.TRUCK_CAP_T; cur = inst["depot_idx"]
            while open_sites and cap_left > 1e-3:
                best = min(open_sites, key=lambda l: inst["D"][cur][inst["ltl_idx"][l]])
                take = min(rem_dem[best], cap_left)
                if take <= 1e-3:
                    open_sites.remove(best); continue
                trial = route + [best]
                _, _, th = ltl_trip_eval(trial, cls, inst)
                if th > P.NIGHT_HOURS and route: break
                route = trial; cap_left -= take
                rem_dem[best] -= take
                if rem_dem[best] <= 1e-3: open_sites.remove(best)
                cur = inst["ltl_idx"][best]
            if route:
                _, _, th = ltl_trip_eval(route, cls, inst)
                if veh_time_left[v] < th - 1e-9:
                    # 该车剩余预算装不下这趟(否则构造解违反车队预算, 巨大罚项污染 T0 与 SA 轨迹)
                    veh_trips_left[v] += 1      # 趟数还回去
                    veh_time_left[v] = 0.0      # 标记该车不可用, 继续尝试别的车
                    continue
                ltl_routes[v].append(route)
                veh_time_left[v] -= th  # 扣时间预算
            else:
                veh_trips_left[v] += 1  # 没用掉, 还回去
                break
    return ftl_ntrip, ltl_routes


def _ltl_remaining(lr, inst):
    """各 LTL 站点的剩余(未装载)需求 —— 模拟 evaluate 的贪心分配。支持一站多趟分装。"""
    dem = {l["id"]: l["demand"] for l in inst["ltl"]}
    served = {lid: 0.0 for lid in dem}
    veh_cls = MF.get_veh_classes(inst)
    for v, trips in lr.items():
        for route in trips:
            _, ld, _ = ltl_trip_eval(route, veh_cls[v], inst)
            rem = ld
            for l in route:
                take = min(dem[l] - served[l], rem); served[l] += take; rem -= take
    return {lid: dem[lid] - served[lid] for lid in dem}


def _ruin_recreate(nlr, inst, rng, veh_cls, ntr_max, budget=None, v_time=None):
    """大邻域(SISR 风格): 以随机站点为种, 按路网距离拆其 2-4 个近邻站点的全部访问
    → 随机顺序、随机可行位重建(保持多样性, 避免贪心重建反复收敛同一模式)。
    整体接受与否由 SA 的精确 evaluate 决定。"""
    ltl_cls = {l["id"]: l["cls"] for l in inst["ltl"]}
    all_sites = sorted({s for trips in nlr.values() for t in trips if t for s in t})
    if not all_sites:
        return
    s0 = rng.choice(all_sites)
    k = min(len(all_sites), rng.randint(2, 4))
    n0 = inst["ltl_idx"][s0]
    near = sorted(all_sites, key=lambda s: inst["D"][n0][inst["ltl_idx"][s]])[:k]
    sites = set(near)
    for v in list(nlr):
        nlr[v] = [[s for s in t if s not in sites] for t in nlr[v] if t]
        nlr[v] = [t for t in nlr[v] if t]
    order = list(sites); rng.shuffle(order)
    for s in order:
        dem_s = next(l["demand"] for l in inst["ltl"] if l["id"] == s)
        for _round in range(6):     # 高需求站可跨多趟分装, 插到装完或无位
            rem_s = _ltl_remaining(nlr, inst)[s]
            if rem_s <= 0.01:
                break
            vs = [v for v in nlr if veh_cls[v] == ltl_cls[s]]
            rng.shuffle(vs)
            pos = []
            for v in vs:
                for ti in range(len(nlr[v])):
                    if s in nlr[v][ti]:
                        continue
                    for p in range(len(nlr[v][ti]) + 1):
                        pos.append((v, ti, p))
                if len([t for t in nlr[v] if t]) < ntr_max:
                    pos.append((v, len(nlr[v]), 0))
            rng.shuffle(pos)
            placed = False
            for (v, ti, p) in pos:
                route = nlr[v][ti] if ti < len(nlr[v]) else []
                nr = route[:p] + [s] + route[p:]
                _, _, th = ltl_trip_eval(nr, veh_cls[v], inst)
                old_th = ltl_trip_eval(route, veh_cls[v], inst)[2] if route else 0.0
                ok_b = True
                if budget is not None and v_time is not None:
                    ok_b = v_time(v) + th - old_th <= budget + 1e-9
                if th <= P.NIGHT_HOURS and ok_b:
                    if ti < len(nlr[v]): nlr[v][ti] = nr
                    else: nlr[v].append(nr)
                    placed = True
                    break
            if not placed:
                break


def solve(inst, time_limit=30, seed=42, trace_path=None, cool=0.99985, max_iters=None,
          disable_ops=None, use_restart=True):
    """SA 主循环。邻域: insert(剩余需求站点插回,支持多趟分装)/drop/relocate(位置插入)/swap/merge/2-opt/FTL(±趟或同类车重指派)。
    温度: T0=2%|最优|, 几何冷却; 冷透后从历史最优重启并半温再热(避免在漂移劣解附近游走)。
    max_iters: 固定迭代预算(报告口径), 使重跑逐位一致(不依赖墙钟/机器负载); None 时按 time_limit 墙钟停止。
    disable_ops: 消融实验用, 如 {"rar"}(关 ruin-recreate) — 其余算子权重按比例重归一,
    默认权重与历史硬编码完全一致(空集时行为逐位不变)。
    use_restart=False: 消融"从最优重启"机制(单链冷却到底)。
    trace_path: 若给定, 把 (墙钟秒, 当前最优成本) 逐次改进轨迹写盘(flush), 供收敛图/审计用。"""
    # 算子权重(与历史硬编码阈值一致: rar .15/ins .15/drop .10/rel .10/swap .10/merge .08/2opt .07/ftl .25)
    _W = [("rar", 0.15), ("insert", 0.15), ("drop", 0.10), ("relocate", 0.10),
          ("swap", 0.10), ("merge", 0.08), ("twopt", 0.07), ("ftl", 0.25)]
    _dis = set(disable_ops or ())
    _w = [(nm, w) for nm, w in _W if nm not in _dis]
    if _dis:
        _tot = sum(w for _, w in _w)
        _thr = {}
        _acc = 0.0
        for _nm, _wv in _w:
            _acc += _wv / _tot
            _thr[_nm] = _acc
    else:
        # 空禁用集: 字面量阈值, 与历史硬编码完全一致(逐位可复现)
        _thr = {"rar": 0.15, "insert": 0.30, "drop": 0.40, "relocate": 0.50,
                "swap": 0.60, "merge": 0.68, "twopt": 0.75}
    _thr[_w[-1][0]] = 1.01   # 末算子兜底(浮点余量)

    def _pick(o):
        for _nm, _ in _w:
            if o < _thr[_nm]:
                return _nm
        return _w[-1][0]
    rng = random.Random(seed)
    veh_cls = MF.get_veh_classes(inst)
    ft, lr = construct(inst, rng); cur_c = evaluate(ft, lr, inst)
    best_ft, best_lr, best_c = copy.deepcopy(ft), copy.deepcopy(lr), cur_c
    t0 = time.time(); it = 0
    T0 = max(1e-6, abs(best_c) * 0.02); T = T0
    ntr_max = inst.get("trips_per_vehicle", 5)
    trace_f = None
    if trace_path:
        os.makedirs(os.path.dirname(trace_path), exist_ok=True)
        trace_f = open(trace_path, "w", newline="", encoding="utf-8")
        trace_f.write("t_s,best_cost\n")
        trace_f.write(f"{time.time()-t0:.2f},{best_c:.2f}\n"); trace_f.flush()
    ltl_cls = {l["id"]: l["cls"] for l in inst["ltl"]}
    _fb = inst.get("fleet_budget")
    budget = _fb if _fb is not None else P.NIGHT_HOURS * ntr_max

    def _v_time(v, nft_d, nlr_d):
        t_ = 0.0
        for (vv, fid), k in nft_d.items():
            if vv == v and k > 0:
                t_ += ftl_trip_cost(v, fid, inst)[1] * k
        for r in nlr_d.get(v, []):
            if r:
                t_ += ltl_trip_eval(r, veh_cls[v], inst)[2]
        return t_

    def _ltl_th(route, v):
        return ltl_trip_eval(route, veh_cls[v], inst)[2] if route else 0.0
    while time.time() - t0 < time_limit and (max_iters is None or it < max_iters):
        it += 1
        nft = copy.deepcopy(ft); nlr = copy.deepcopy(lr)
        op = rng.random()
        _opn = _pick(op)
        if _opn == "rar":  # ruin-and-recreate: 拆 2-4 站贪心重建(跳出成对邻域)
            _ruin_recreate(nlr, inst, rng, veh_cls, ntr_max, budget=budget,
                           v_time=lambda v: _v_time(v, nft, nlr))
        elif _opn == "insert":  # insert: 有剩余需求的站点(含部分已装, 支持多趟分装) → 同类车可行位置
            remaining = _ltl_remaining(nlr, inst)
            cands = [lid for lid, r in remaining.items() if r > 0.01]
            if cands:
                s = rng.choice(cands)
                vs = [v for v in nlr if veh_cls[v] == ltl_cls[s]]
                rng.shuffle(vs)
                placed = False
                for v in vs:
                    pos = [(ti, p) for ti in range(len(nlr[v])) for p in range(len(nlr[v][ti]) + 1)
                           if s not in nlr[v][ti]]      # 同趟不重复(MIP lonce)
                    if len([t for t in nlr[v] if t]) < ntr_max:
                        pos.append((len(nlr[v]), 0))          # 允许开新趟
                    rng.shuffle(pos)
                    for (ti, p) in pos:
                        route = nlr[v][ti] if ti < len(nlr[v]) else []
                        nr = route[:p] + [s] + route[p:]
                        _, _, th = ltl_trip_eval(nr, veh_cls[v], inst)
                        if th <= P.NIGHT_HOURS and _v_time(v, nft, nlr) + th - _ltl_th(route, v) <= budget + 1e-9:
                            if ti < len(nlr[v]): nlr[v][ti] = nr
                            else: nlr[v].append(nr)
                            placed = True; break
                    if placed: break
        elif _opn == "drop":  # drop: 放弃站点(→ shortage, 省趟固定成本)
            vs = [v for v in nlr if nlr[v]]
            if vs:
                v = rng.choice(vs); trips = [t for t in nlr[v] if t]
                if trips:
                    ti = rng.randrange(len(trips))
                    if trips[ti]: trips[ti].pop(rng.randrange(len(trips[ti])))
                    nlr[v] = [t for t in nlr[v] if t]
        elif _opn == "relocate":  # relocate: 移站点到另一同类车的现有趟内位置(无位则新趟)
            vs = [v for v in nlr if nlr[v]]
            if vs:
                v = rng.choice(vs); trips = [t for t in nlr[v] if t]
                if trips:
                    ti = rng.randrange(len(trips)); r = trips[ti]
                    if r:
                        s = r.pop(rng.randrange(len(r)))
                        nlr[v] = [t for t in nlr[v] if t]
                        v2 = rng.choice([vv for vv in nlr if veh_cls[vv] == veh_cls[v]])
                        pos = [(t2, p) for t2 in range(len(nlr[v2])) for p in range(len(nlr[v2][t2]) + 1)
                               if s not in nlr[v2][t2]]
                        if len([t for t in nlr[v2] if t]) < ntr_max:
                            pos.append((len(nlr[v2]), 0))
                        rng.shuffle(pos)
                        placed = False
                        for (t2, p) in pos:
                            route = nlr[v2][t2] if t2 < len(nlr[v2]) else []
                            nr = route[:p] + [s] + route[p:]
                            _, _, th = ltl_trip_eval(nr, veh_cls[v2], inst)
                            if th <= P.NIGHT_HOURS and _v_time(v2, nft, nlr) + th - _ltl_th(route, v2) <= budget + 1e-9:
                                if t2 < len(nlr[v2]): nlr[v2][t2] = nr
                                else: nlr[v2].append(nr)
                                placed = True; break
                        if not placed:
                            if _v_time(v2, nft, nlr) + _ltl_th([s], v2) <= budget + 1e-9:
                                nlr[v2].append([s])
        elif _opn == "swap":  # swap: 两同类趟间换站(防同趟重复)
            vs = [v for v in nlr if nlr[v]]
            if vs:
                v1 = rng.choice(vs); trips1 = [t for t in nlr[v1] if t]
                t1 = rng.choice(trips1); p1 = rng.randrange(len(t1))
                v2 = rng.choice([v for v in vs if veh_cls[v] == veh_cls[v1]])
                trips2 = [t for t in nlr[v2] if t]
                t2 = rng.choice(trips2); p2 = rng.randrange(len(t2))
                s1, s2 = t1[p1], t2[p2]
                if s1 != s2 and s1 not in t2 and s2 not in t1:
                    nt1 = list(t1); nt1[p1] = s2
                    nt2 = list(t2); nt2[p2] = s1
                    ok1 = _v_time(v1, nft, nlr) + _ltl_th(nt1, v1) - _ltl_th(t1, v1) <= budget + 1e-9
                    ok2 = _v_time(v2, nft, nlr) + _ltl_th(nt2, v2) - _ltl_th(t2, v2) <= budget + 1e-9
                    if ok1 and ok2:
                        t1[p1], t2[p2] = s2, s1
        elif _opn == "merge":  # merge: 同车两趟合并(预检夜间窗, 避免 1e9 罚项评估)
            vs = [v for v in nlr if len([t for t in nlr[v] if t]) >= 2]
            if vs:
                v = rng.choice(vs); trips = [t for t in nlr[v] if t]
                i, j = rng.sample(range(len(trips)), 2)
                merged = trips[i] + trips[j]
                _, ld, th = ltl_trip_eval(merged, veh_cls[v], inst)
                if (ld <= P.TRUCK_CAP_T and th <= P.NIGHT_HOURS
                        and _v_time(v, nft, nlr) + th - _ltl_th(trips[i], v) - _ltl_th(trips[j], v) <= budget + 1e-9):
                    nlr[v] = [t for k, t in enumerate(trips) if k not in (i, j)] + [merged]
        elif _opn == "twopt":  # 2-opt: 趟内段反转(≥3 站)
            vs = [v for v in nlr if nlr[v]]
            if vs:
                v = rng.choice(vs); trips = [t for t in nlr[v] if len(t) >= 3]
                if trips:
                    r = rng.choice(trips); i, j = sorted(rng.sample(range(len(r)), 2))
                    r[i:j+1] = r[i:j+1][::-1]
        else:  # FTL(=ftl 算子): 增减趟 或 同类车间重指派 1 趟
            keys = [kk for kk, n in nft.items() if n > 0]
            if rng.random() < 0.5 and keys:
                kk = rng.choice(keys)
                dv = rng.choice([-1, 1])
                add_h = ftl_trip_cost(kk[0], kk[1], inst)[1] if dv > 0 else 0.0
                if dv < 0 or _v_time(kk[0], nft, nlr) + add_h <= budget + 1e-9:
                    nft[kk] = max(0, nft[kk] + dv)
            else:
                fids = {f["id"] for f in inst["ftl"]}
                srcs = [kk for kk in keys if kk[1] in fids]
                if srcs:
                    (sv, fid) = rng.choice(srcs)
                    tgt = [v for v in range(inst["n_vehicles"])
                           if veh_cls[v] == next(f["cls"] for f in inst["ftl"] if f["id"] == fid)]
                    mv_h = ftl_trip_cost(sv, fid, inst)[1]
                    tgt = [v for v in tgt if v == sv or _v_time(v, nft, nlr) + mv_h <= budget + 1e-9]
                    if tgt:
                        nft[(sv, fid)] -= 1
                        tv = rng.choice(tgt)
                        nft[(tv, fid)] = nft.get((tv, fid), 0) + 1
        cc = evaluate(nft, nlr, inst)
        d = cc - cur_c
        if d < 0 or rng.random() < math.exp(-d / max(T, 1e-3)):
            ft, lr, cur_c = nft, nlr, cc
            if cc < best_c:
                best_ft, best_lr, best_c = copy.deepcopy(nft), copy.deepcopy(nlr), cc
                if trace_f:
                    trace_f.write(f"{time.time()-t0:.2f},{best_c:.2f}\n"); trace_f.flush()
        T *= cool
        if use_restart and T < T0 * 1e-3:   # 冷透: 从历史最优重启, 半温再热(消融可关)
            ft, lr, cur_c = copy.deepcopy(best_ft), copy.deepcopy(best_lr), best_c
            T = T0 * 0.5
    if trace_f:
        trace_f.write(f"{time.time()-t0:.2f},{best_c:.2f}\n")
        trace_f.close()
    return best_ft, best_lr, best_c, dict(iters=it)


if __name__ == "__main__":
    import pulp
    # 先 tiny 对齐验证
    inst = MF.gen_instance(3, 8, 6, seed=42, use_real_net=True, trips_per_vehicle=3)
    t0 = time.time(); ft, lr, hc, hm = solve(inst, time_limit=12, seed=42); ht = time.time() - t0
    t0 = time.time(); m, vv = MF.build_mip(inst, time_limit=120, gap=0.05); ct = time.time() - t0
    cpx = pulp.value(m.objective)
    print(f"tiny: HEU {hc/1e6:.4f}M({ht:.0f}s) | CPLEX {cpx/1e6:.4f}M({ct:.0f}s) | gap={(hc-cpx)/cpx*100:.2f}%")
