# -*- coding: utf-8 -*-
"""E1(R1.2/R2.7): 真 ALNS 基准 —— Ropke-Pisinger 框架的忠实实现。

设计裁定(response to comments.md v2 〇-B):
- destroy 档案: random / spatially-related / worst-contribution 移除(LTL 侧) + FTL 趟拆减(FTL 侧);
- repair 档案: greedy 插入(最小行程增量) / regret 插入(次优-最优差最大者先插);
- 分段自适应权重(段长 100): 新全局最优 +3 / 改进当前 +2 / 接受 +1, rho=0.5 衰减;
- 接受准则与 SA 完全一致(T0=2%|best|, 几何冷却 0.99985, 冷透从最优重启半温再热);
- 停止语义与 SA/ILS 统一: 固定迭代与墙钟双检查;
- 一切评价/可行性复用 mixfleet_heuristic(ltl_trip_eval/ftl_trip_cost/evaluate), 报告成本一律 reprice。
输出: results/tables/alns_bench.csv
"""
import os, sys, csv, time, copy, math, random, glob
sys.path.insert(0, os.path.dirname(__file__))
import params as P
import mixfleet_model as MF, mixfleet_heuristic as MH
import inst_config as CFG, reprice as RP

TBL = os.path.join(CFG.ROOT, "results", "tables")
OUT = os.path.join(TBL, "alns_bench.csv")

SEG = 100          # 自适应分段长度
RHO = 0.5          # 权重衰减
SCORE_BEST, SCORE_IMP, SCORE_ACC = 3.0, 2.0, 1.0
DESTROYS = ["random", "related", "worst", "ftl"]
REPAIRS = ["greedy", "regret"]


# ---------- 评价辅助 ----------
def _ltl_th(route, v, veh_cls, inst):
    return MH.ltl_trip_eval(route, veh_cls[v], inst)[2] if route else 0.0


def _v_time(v, nft, nlr, veh_cls, inst):
    t_ = 0.0
    for (vv, fid), k in nft.items():
        if vv == v and k > 0:
            t_ += MH.ftl_trip_cost(v, fid, inst)[1] * k
    for r in nlr.get(v, []):
        if r:
            t_ += MH.ltl_trip_eval(r, veh_cls[v], inst)[2]
    return t_


def _remaining_ltl(nlr, inst):
    dem = {l["id"]: l["demand"] for l in inst["ltl"]}
    served = {lid: 0.0 for lid in dem}
    for v, trips in nlr.items():
        for route in trips:
            rem = P.TRUCK_CAP_T
            for l in route:
                ld = min(dem[l] - served[l], rem)
                served[l] += ld; rem -= ld
    return {lid: dem[lid] - served[lid] for lid in dem}


# ---------- destroy 算子 ----------
def _strip_sites(nlr, sites):
    for v in list(nlr):
        nlr[v] = [[s for s in t if s not in sites] for t in nlr[v] if t]
        nlr[v] = [t for t in nlr[v] if t]


def destroy_random(nlr, nft, inst, rng, veh_cls, budget):
    all_sites = sorted({s for trips in nlr.values() for t in trips if t for s in t})
    if not all_sites:
        return set()
    kmax = max(6, math.ceil(0.3 * len(all_sites)))
    k = rng.randint(2, min(kmax, len(all_sites)))
    sites = set(rng.sample(all_sites, k))
    _strip_sites(nlr, sites)
    return sites


def destroy_related(nlr, nft, inst, rng, veh_cls, budget):
    all_sites = sorted({s for trips in nlr.values() for t in trips if t for s in t})
    if not all_sites:
        return set()
    s0 = rng.choice(all_sites)
    kmax = max(6, math.ceil(0.3 * len(all_sites)))
    k = rng.randint(2, min(kmax, len(all_sites)))
    n0 = inst["ltl_idx"][s0]
    near = sorted(all_sites, key=lambda s: inst["D"][n0][inst["ltl_idx"][s]])[:k]
    sites = set(near)
    _strip_sites(nlr, sites)
    return sites


def destroy_worst(nlr, nft, inst, rng, veh_cls, budget):
    """按行程节省估计选最贵站点: Σ(绕行差)c_km + 空趟摊派 F_trip(路径含汇, 与评价同构)。"""
    saving = {}
    for v, trips in nlr.items():
        knode = inst["sink_idx"][MF.sink_for_class(veh_cls[v], inst)["id"]]
        for route in trips:
            prev = inst["depot_idx"]
            for i, s in enumerate(route):
                nxt = inst["ltl_idx"][route[i + 1]] if i + 1 < len(route) else knode
                node = inst["ltl_idx"][s]
                saving[s] = saving.get(s, 0.0) + \
                    (inst["D"][prev][node] + inst["D"][node][nxt] - inst["D"][prev][nxt]) * P.TRIP_PER_KM
                if len(route) == 1:
                    saving[s] += P.TRIP_FIXED
                prev = node
    if not saving:
        return set()
    order = sorted(saving, key=lambda s: -saving[s])
    k = rng.randint(2, min(6, len(order)))
    take = set(order[:k - 1]) | {rng.choice(order)}          # 最贵 + 随机扰动(标准做法)
    _strip_sites(nlr, take)
    return take


def destroy_ftl(nlr, nft, inst, rng, veh_cls, budget):
    """FTL 侧拆减: 随机 (v,fid) 减 1-2 趟(制造未服务吨位交由 repair)。"""
    cand = [(v, fid) for (v, fid), k in nft.items() if k > 0]
    if not cand:
        return set()
    v, fid = rng.choice(cand)
    nft[(v, fid)] = max(0, nft[(v, fid)] - rng.randint(1, 2))
    return set()


# ---------- repair 算子 ----------
def _insert_positions(nlr, inst, veh_cls, s, ntr_max):
    ltl_cls = {l["id"]: l["cls"] for l in inst["ltl"]}
    for v in nlr:
        if veh_cls[v] != ltl_cls[s]:
            continue
        for ti in range(len(nlr[v])):
            if s in nlr[v][ti]:
                continue
            for p in range(len(nlr[v][ti]) + 1):
                yield (v, ti, p)
        if len([t for t in nlr[v] if t]) < ntr_max:
            yield (v, len(nlr[v]), 0)


NEAR_ROUTES = 6      # 空间邻域: 仅在与站点最近的 R 条同类路线内找位(canonical 邻域限制)


def _near_routes(nlr, inst, veh_cls, s):
    """按路线内最近节点到 s 的距离, 返回同类车中最近的 R 条路线 id 集合(含空趟候选)。"""
    ltl_cls = {l["id"]: l["cls"] for l in inst["ltl"]}
    node = inst["ltl_idx"][s]
    scored = []
    for v in nlr:
        if veh_cls[v] != ltl_cls[s]:
            continue
        for ti, route in enumerate(nlr[v]):
            if not route:
                continue
            prox = min(inst["D"][node][inst["ltl_idx"][x]] for x in route)
            scored.append((prox, (v, ti)))
    scored.sort()
    return {rt for _, rt in scored[:NEAR_ROUTES]}


def _insert_scan(nlr, nft, inst, veh_cls, s, budget, ntr_max, vt):
    """扫描 s 的可行插入位(空间邻域限制: 最近 R 条同类路线 + 新趟); vt 为每车时间缓存。
    返回 [(delta_cost, pos, th_new, th_old)], 已按可行性(夜窗+预算)过滤。"""
    near = _near_routes(nlr, inst, veh_cls, s)
    out = []
    for pos in _insert_positions(nlr, inst, veh_cls, s, ntr_max):
        v, ti, p = pos
        if ti < len(nlr[v]) and (v, ti) not in near:
            continue
        route = nlr[v][ti] if ti < len(nlr[v]) else []
        nr = route[:p] + [s] + route[p:]
        _, _, th = MH.ltl_trip_eval(nr, veh_cls[v], inst)
        old_th = _ltl_th(route, v, veh_cls, inst)
        if th <= P.NIGHT_HOURS and vt[v] + th - old_th <= budget + 1e-9:
            dn = MH.ltl_trip_eval(nr, veh_cls[v], inst)[0]
            do = MH.ltl_trip_eval(route, veh_cls[v], inst)[0] if route else 0.0
            out.append((dn - do, pos, th, old_th))
    return out


def _vt_cache(nlr, nft, inst, veh_cls):
    return {v: _v_time(v, nft, nlr, veh_cls, inst) for v in nlr}


def _do_insert(nlr, pos, s):
    v, ti, p = pos
    route = nlr[v][ti] if ti < len(nlr[v]) else []
    nr = route[:p] + [s] + route[p:]
    if ti < len(nlr[v]):
        nlr[v][ti] = nr
    else:
        nlr[v].append(nr)


def _try_insert(nlr, nft, inst, veh_cls, s, budget, ntr_max, chooser):
    """插入站点 s 的全部剩余吨位; chooser(cands) 返回选定位置。每车时间缓存避免全量重算。"""
    rem_s = _remaining_ltl(nlr, inst)[s]
    if rem_s <= 0.01:
        return False
    placed = False
    while rem_s > 0.01:
        vt = _vt_cache(nlr, nft, inst, veh_cls)
        cands = _insert_scan(nlr, nft, inst, veh_cls, s, budget, ntr_max, vt)
        if not cands:
            break
        cands.sort(key=lambda x: x[0])
        pos = chooser(cands)
        _do_insert(nlr, pos, s)
        placed = True
        rem_s = _remaining_ltl(nlr, inst)[s]
    return placed


def _local_polish(nlr, nft, inst, veh_cls, budget, ntr_max, sweeps=3, touched=None):
    """education 步(ALNS 文献常规): 插入后对 LTL 路线做 relocate+2-opt 严格改进下降,
    预算/夜窗可行性经每车时间缓存校验。仅动 LTL 结构, FTL 趟数不变。"""
    ltl_cls = {l["id"]: l["cls"] for l in inst["ltl"]}
    for _sw in range(sweeps):
        improved = False
        vt = _vt_cache(nlr, nft, inst, veh_cls)
        # 2-opt(段反转) per route
        for v in list(nlr):
            if touched and v not in touched:
                continue
            for ti in range(len(nlr[v])):
                route = nlr[v][ti]
                if len(route) < 3:
                    continue
                base = MH.ltl_trip_eval(route, veh_cls[v], inst)[0]
                for i in range(len(route) - 1):
                    for j in range(i + 2, len(route)):
                        nr = route[:i] + route[i:j + 1][::-1] + route[j + 1:]
                        th = MH.ltl_trip_eval(nr, veh_cls[v], inst)[2]
                        if th <= P.NIGHT_HOURS:
                            nc = MH.ltl_trip_eval(nr, veh_cls[v], inst)[0]
                            if nc < base - 1e-9:
                                old_th = MH.ltl_trip_eval(route, veh_cls[v], inst)[2]
                                if vt[v] + th - old_th <= budget + 1e-9:
                                    nlr[v][ti] = nr
                                    vt[v] += th - old_th
                                    base, improved = nc, True
                                    route = nr
        if not improved:
            break


def repair_greedy(un_ltl, nft, nlr, inst, veh_cls, budget, ntr_max, rng, touched=None):
    touched = touched if touched is not None else set()
    _repair_ftl(nft, nlr, inst, veh_cls, budget)
    pending = {s for s in un_ltl if _remaining_ltl(nlr, inst).get(s, 0) > 0.01}
    while pending:
        # 标准全局最优贪心: 每轮在全部待插站点中选全局最小增量位
        vt = _vt_cache(nlr, nft, inst, veh_cls)
        best = None
        drop = []
        for s in pending:
            cands = _insert_scan(nlr, nft, inst, veh_cls, s, budget, ntr_max, vt)
            if not cands:
                drop.append(s); continue
            cands.sort(key=lambda x: x[0])
            if best is None or cands[0][0] < best[0]:
                best = (cands[0][0], s, cands[0][1])
        for s in drop:
            pending.discard(s)
        if best is None:
            break
        _, s, pos = best
        _do_insert(nlr, pos, s)
        touched.add(pos[0])
        if _remaining_ltl(nlr, inst)[s] <= 0.01:
            pending.discard(s)
    if globals().get('USE_POLISH', True):
        _local_polish(nlr, nft, inst, veh_cls, budget, ntr_max, touched=touched)


def repair_regret(un_ltl, nft, nlr, inst, veh_cls, budget, ntr_max, rng, touched=None):
    touched = touched if touched is not None else set()
    ltl_cls = {l["id"]: l["cls"] for l in inst["ltl"]}
    _repair_ftl(nft, nlr, inst, veh_cls, budget)
    pending = {s for s in un_ltl if _remaining_ltl(nlr, inst).get(s, 0) > 0.01}
    while pending:
        # 每轮选 regret 最大者(次优-最优差); 只装一轮, 重新计算(近似标准 regret-2)
        best_pick, best_regret, best_pos = None, -1e18, None
        drop = []
        vt = _vt_cache(nlr, nft, inst, veh_cls)
        for s in pending:
            cands = _insert_scan(nlr, nft, inst, veh_cls, s, budget, ntr_max, vt)
            if not cands:
                drop.append(s); continue
            cands.sort(key=lambda x: x[0])
            regret = (cands[1][0] - cands[0][0]) if len(cands) > 1 else 1e9
            if regret > best_regret:
                best_regret, best_pick, best_pos = regret, s, cands[0][1]
        for s in drop:
            pending.discard(s)
        if best_pick is None:
            break
        _do_insert(nlr, best_pos, best_pick)
        touched.add(best_pos[0])
        if _remaining_ltl(nlr, inst)[best_pick] <= 0.01:
            pending.discard(best_pick)
        touched.add(best_pos[0]); touched.add(best_pos[0])
    if globals().get('USE_POLISH', True):
        _local_polish(nlr, nft, inst, veh_cls, budget, ntr_max, touched=touched)


def _repair_ftl(nft, nlr, inst, veh_cls, budget):
    """把 FTL 未服务吨按可行车补趟(装完或无可行车为止)。"""
    dem = {f["id"]: f["demand"] for f in inst["ftl"]}
    trips = {}
    for (v, fid), k in nft.items():
        if k > 0:
            trips[fid] = trips.get(fid, 0) + k
    for f in inst["ftl"]:
        fid = f["id"]
        need = math.ceil(f["demand"] / P.TRUCK_CAP_T) - trips.get(fid, 0)
        vs = [v for v in range(inst["n_vehicles"]) if veh_cls[v] == f["cls"]]
        while need > 0 and vs:
            v = min(vs, key=lambda x: _v_time(x, nft, nlr, veh_cls, inst))
            th = MH.ftl_trip_cost(v, fid, inst)[1]
            if _v_time(v, nft, nlr, veh_cls, inst) + th <= budget + 1e-9:
                nft[(v, fid)] = nft.get((v, fid), 0) + 1
                need -= 1
            else:
                vs.remove(v)


# ---------- ALNS 主循环 ----------
def solve_alns(inst, time_limit=60, seed=42, max_iters=None, trace_path=None, use_polish=True):
    global USE_POLISH
    USE_POLISH = use_polish
    rng = random.Random(seed)
    veh_cls = MF.get_veh_classes(inst)
    ft, lr = MH.construct(inst, rng)
    cur_c = MH.evaluate(ft, lr, inst)
    best_ft, best_lr, best_c = copy.deepcopy(ft), copy.deepcopy(lr), cur_c
    t0 = time.time(); it = 0
    T0 = max(1e-6, abs(best_c) * 0.02); T = T0
    ntr_max = inst.get("trips_per_vehicle", 5)
    _fb = inst.get("fleet_budget")
    budget = _fb if _fb is not None else P.NIGHT_HOURS * ntr_max
    dw = {d: 1.0 for d in DESTROYS}; rw = {r: 1.0 for r in REPAIRS}
    dseg = {d: [0.0, 0] for d in DESTROYS}; rseg = {r: [0.0, 0] for r in REPAIRS}
    trace_f = None
    if trace_path:
        os.makedirs(os.path.dirname(trace_path), exist_ok=True)
        trace_f = open(trace_path, "w", newline="", encoding="utf-8")
        trace_f.write("t_s,best_cost\n"); trace_f.write(f"0.0,{best_c:.2f}\n"); trace_f.flush()

    def _roulette(w):
        r = rng.random() * sum(w.values())
        acc = 0.0
        for k, v_ in w.items():
            acc += v_
            if r <= acc:
                return k
        return list(w)[-1]

    destroy_fn = {"random": destroy_random, "related": destroy_related,
                  "worst": destroy_worst, "ftl": destroy_ftl}
    repair_fn = {"greedy": repair_greedy, "regret": repair_regret}

    while (max_iters is None or it < max_iters) and (time_limit is None or time.time() - t0 < time_limit):
        it += 1
        dk = _roulette(dw); rk = _roulette(rw)
        nft = copy.deepcopy(ft); nlr = copy.deepcopy(lr)
        removed = destroy_fn[dk](nlr, nft, inst, rng, veh_cls, budget)
        touched = set()
        repair_fn[rk](removed, nft, nlr, inst, veh_cls, budget, ntr_max, rng, touched)
        c_new = MH.evaluate(nft, nlr, inst)
        d_score = r_score = 0.0
        if c_new < best_c - 1e-9:
            best_ft, best_lr, best_c = copy.deepcopy(nft), copy.deepcopy(nlr), c_new
            d_score = r_score = SCORE_BEST
            if trace_f:
                trace_f.write(f"{time.time()-t0:.2f},{best_c:.2f}\n"); trace_f.flush()
        elif c_new < cur_c - 1e-9:
            d_score = r_score = SCORE_IMP
        if c_new < cur_c - 1e-9 or rng.random() < math.exp(-max(0.0, c_new - cur_c) / max(T, 1e-9)):
            ft, lr, cur_c = nft, nlr, c_new
            if d_score == 0.0:
                d_score = r_score = SCORE_ACC
        else:
            d_score = r_score = 0.0
        T *= 0.99985
        if T < 1e-3 * T0:
            ft, lr = copy.deepcopy(best_ft), copy.deepcopy(best_lr)
            cur_c = best_c; T = 0.5 * T0
        dseg[dk][0] += d_score; dseg[dk][1] += 1
        rseg[rk][0] += r_score; rseg[rk][1] += 1
        if it % SEG == 0:
            # 权重下限 0.05 防退化(未用算子衰减到 0 后将永不被选, 失去档案多样性)
            for k in DESTROYS:
                s_, u_ = dseg[k]
                dw[k] = max(0.05, RHO * dw[k] + (1 - RHO) * (s_ / max(1, u_)))
                dseg[k] = [0.0, 0]
            for k in REPAIRS:
                s_, u_ = rseg[k]
                rw[k] = max(0.05, RHO * rw[k] + (1 - RHO) * (s_ / max(1, u_)))
                rseg[k] = [0.0, 0]
    if trace_f:
        trace_f.close()
    return best_ft, best_lr, best_c, dict(iters=it, dw=dw, rw=rw), time.time() - t0


# ---------- 运行器 ----------
def gen_inst(tag):
    if tag == "XL":
        vc = []
        for c in CFG.CLASSES:
            vc += [c] * {"earth": 7, "demolition": 10, "renovation": 7}[c]
        return MF.gen_instance(7, 32, len(vc), seed=7, use_real_net=True,
                               trips_per_vehicle=CFG.R, veh_classes=vc,
                               fleet_budget=float(P.NIGHT_HOURS))
    return CFG.gen(tag, 42)


def family_insts():
    """认证族 + 大族(各10), 复用 scale_study 结果集的实例口径。"""
    import scale_study.gen_scale as GS
    out = []
    for name in ("scale_small_final", "scale_large"):
        path = os.path.join(CFG.ROOT, "results", "scale_study", name + ".csv")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                out.append((name, r["size_id"], int(r["seed"]), int(r["nf"]), int(r["nl"]),
                            int(r["veh"]), r["size_id"]))
    return out


def main():
    rows = []
    tags = ["S", "M", "L", "X", "XL"]
    for tag in tags:
        inst = gen_inst(tag)
        stime = CFG.SA_TIME.get(tag, 180)
        siters = CFG.SA_ITERS.get(tag)
        # 今晚首跑: 墙钟口径记录迭代数; 正式数字按 ILS 先例做 calibrate-then-fixed 二跑
        ft, lr, hc, hm, wt = solve_alns(inst, time_limit=stime, seed=42, max_iters=None)
        rc, rstat = RP.reprice(inst, ft, lr)
        with open(os.path.join(TBL, "mixfleet_bench.csv"), encoding="utf-8-sig") as fh:
            mx = next(r for r in csv.DictReader(fh) if r["instance"].startswith(tag + ":"))
        gap = 100.0 * (rc - float(mx["cpx_cost"])) / float(mx["cpx_cost"])
        rows.append(dict(instance=tag, alns_reprice=f"{rc:.0f}", reprice_status=rstat,
                         time_s=f"{wt:.0f}", iters=hm["iters"], budget_s=stime,
                         cpx_incumbent=mx["cpx_cost"], gap_inc_pct=f"{gap:.2f}",
                         sa_reprice=mx["heu_cost"], alns_vs_sa_pct=f"{100.0*(rc-float(mx['heu_cost']))/float(mx['heu_cost']):.2f}"))
        print(f"{tag}: ALNS reprice {rc:.0f} gap {gap:.2f}% ({hm['iters']} it, {wt:.0f}s)", flush=True)
        with open(OUT, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader(); w.writerows(rows)
    print("saved ->", OUT, flush=True)


if __name__ == "__main__":
    main()
