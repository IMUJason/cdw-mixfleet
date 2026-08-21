#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""教科书 ILS 基线(Lourenco/Martin/Stutzle 2003), 与 SA 完全一致的评估与预算协议:
贪心构造 -> 确定性首改进下降(插入/relocate/swap/2-opt/FTL±趟) ->
随机拆 2-4 站重建(扰动) -> 回最优重启, 循环至固定周期数(逐位可复现)。
报告口径: 全部走 reprice.reprice(结构固定/载荷自由 LP), 与 SA 同源。"""
import random, copy, time

import mixfleet_heuristic as MH
import mixfleet_model as MF
import params as P

PASS_CAP = 3           # 下降阶段轮数上限(单遍首改进 VND 式, 确定性; 控制单轮下降成本)


def snap_lr(lr):
    return {v: [list(t) for t in ts] for v, ts in lr.items()}


def v_time_all(ft, lr, inst, veh_cls):
    """每车已用时间(一次算好, 候选循环内按增量修正)。"""
    t_ = {v: 0.0 for v in range(inst["n_vehicles"])}
    for (vv, fid), k in ft.items():
        if k > 0:
            t_[vv] += MH.ftl_trip_cost(vv, fid, inst)[1] * k
    for v, ts in lr.items():
        for r in ts:
            if r:
                _, _, th = MH.ltl_trip_eval(r, veh_cls[v], inst)
                t_[v] += th
    return t_


def _insert_positions(lr, veh_cls, cls, ntr_max, exclude_site=None):
    """同类车全部可行 (v, 趟下标, 站内位置); 趟下标==len 表示新开一趟(槽位允许时)。
    exclude_site: 跳过已含该站点的路线 —— MIP 约束每趟每站至多一次。"""
    out = []
    for v in lr:
        if veh_cls[v] != cls:
            continue
        for tj in range(len(lr[v])):
            if exclude_site is not None and exclude_site in lr[v][tj]:
                continue
            for pj in range(len(lr[v][tj]) + 1):
                out.append((v, tj, pj))
        if len(lr[v]) < ntr_max:
            out.append((v, len(lr[v]), 0))
    return out


def _try_insert_best(s, ft, lr, inst, veh_cls, accept_if_improves=False):
    """把站点 s 的剩余需求以最优位贪心插入(跨多趟直至装完或无位)。
    accept_if_improves=True 时只在整解成本下降才落位(下降阶段用)。"""
    ntr_max = inst.get("trips_per_vehicle", 5)
    budget = inst.get("fleet_budget", P.NIGHT_HOURS * ntr_max)
    cls = next(l["cls"] for l in inst["ltl"] if l["id"] == s)
    moved = False
    for _round in range(6):
        rem = MH._ltl_remaining(lr, inst)[s]
        if rem <= 0.01:
            break
        best = None
        vt = v_time_all(ft, lr, inst, veh_cls)   # 轮内结构不变, 一次算好
        for (v1, tj, pj) in _insert_positions(lr, veh_cls, cls, ntr_max, exclude_site=s):
            base = lr[v1][tj] if tj < len(lr[v1]) else []
            nr = base[:pj] + [s] + base[pj:]
            _, _, th = MH.ltl_trip_eval(nr, veh_cls[v1], inst)
            if th > P.NIGHT_HOURS:
                continue
            old_th = MH.ltl_trip_eval(base, veh_cls[v1], inst)[2] if base else 0.0
            if vt[v1] + th - old_th > budget + 1e-9:
                continue
            d_cost = (MH.ltl_trip_eval(nr, veh_cls[v1], inst)[0]
                      - (MH.ltl_trip_eval(base, veh_cls[v1], inst)[0] if base else 0.0))
            take = min(rem, P.TRUCK_CAP_T)
            if best is None or d_cost / take < best[0]:
                best = (d_cost / take, v1, tj, nr)
        if best is None:
            break
        _, v1, tj, nr = best
        if accept_if_improves:
            before = MH.evaluate(ft, lr, inst)
            if tj < len(lr[v1]):
                old = lr[v1][tj]; lr[v1][tj] = nr
            else:
                lr[v1].append(nr); old = None
            if MH.evaluate(ft, lr, inst) < before - 1e-9:
                moved = True
            else:                                   # 还原
                if old is None:
                    lr[v1].pop()
                else:
                    lr[v1][tj] = old
                return moved
        else:
            if tj < len(lr[v1]):
                lr[v1][tj] = nr
            else:
                lr[v1].append(nr)
            moved = True
    return moved


def local_search(ft, lr, inst, veh_cls):
    """确定性首改进下降: 插入未服务需求 -> relocate -> swap -> 2-opt -> FTL±趟,
    整轮扫描重复至某轮无改进(或 PASS_CAP)。无任何时间依赖。"""
    ntr_max = inst.get("trips_per_vehicle", 5)
    budget = inst.get("fleet_budget", P.NIGHT_HOURS * ntr_max)
    ltl_cls = {l["id"]: l["cls"] for l in inst["ltl"]}
    improved_any = True
    n_pass = 0
    while improved_any and n_pass < PASS_CAP:
        n_pass += 1
        improved_any = False
        # (a) 插入剩余需求(仅当降本)
        for l in inst["ltl"]:
            if MH._ltl_remaining(lr, inst)[l["id"]] > 0.01:
                if _try_insert_best(l["id"], ft, lr, inst, veh_cls, accept_if_improves=True):
                    improved_any = True
        # (b) relocate: 单次访问迁往任意同类可行位(首改进)
        occ = [(v, ti, pi) for v in lr for ti in range(len(lr[v])) for pi in range(len(lr[v][ti]))]
        for (v0, t0, p0) in occ:
            if t0 >= len(lr[v0]) or p0 >= len(lr[v0][t0]):
                continue
            s0 = lr[v0][t0][p0]
            pre = snap_lr(lr)                       # 无改进时的精确还原锚点
            del lr[v0][t0][p0]
            if not lr[v0][t0]:
                lr[v0] = [t for t in lr[v0] if t]
            c0 = MH.evaluate(ft, lr, inst)
            vt = v_time_all(ft, lr, inst, veh_cls)
            best = None
            for (v1, tj, pj) in _insert_positions(lr, veh_cls, ltl_cls[s0], ntr_max,
                                                  exclude_site=s0):
                base = lr[v1][tj] if tj < len(lr[v1]) else []
                nr = base[:pj] + [s0] + base[pj:]
                _, _, th = MH.ltl_trip_eval(nr, veh_cls[v1], inst)
                if th > P.NIGHT_HOURS:
                    continue
                old_th = MH.ltl_trip_eval(base, veh_cls[v1], inst)[2] if base else 0.0
                if vt[v1] + th - old_th > budget + 1e-9:
                    continue
                if tj < len(lr[v1]):
                    lr[v1][tj] = nr
                else:
                    lr[v1].append(nr)
                c1 = MH.evaluate(ft, lr, inst)
                if c1 < c0 - 1e-9 and (best is None or c1 < best[0]):
                    best = (c1, snap_lr(lr))
                if tj < len(lr[v1]):
                    lr[v1][tj] = base
                else:
                    lr[v1].pop()
            if best is not None:
                lr = best[1]
                improved_any = True
            else:
                lr = pre                             # 精确还原, 保持下降单调
        # (c) swap: 同类两条路线间换站(首改进)
        occ = [(v, ti, pi) for v in lr for ti in range(len(lr[v])) for pi in range(len(lr[v][ti]))]
        for i0 in range(len(occ)):
            v0, t0, p0 = occ[i0]
            if t0 >= len(lr[v0]) or p0 >= len(lr[v0][t0]):
                continue
            s0 = lr[v0][t0][p0]
            for i1 in range(i0 + 1, len(occ)):
                v1, t1, p1 = occ[i1]
                if (v0, t0) == (v1, t1):
                    continue
                if t1 >= len(lr[v1]) or p1 >= len(lr[v1][t1]):
                    continue
                s1 = lr[v1][t1][p1]
                if veh_cls[v0] != veh_cls[v1] or ltl_cls[s0] != ltl_cls[s1]:
                    continue
                if s1 in lr[v0][t0] or s0 in lr[v1][t1]:   # 换入会产生同趟重复访问
                    continue
                snap = snap_lr(lr)
                lr[v0][t0][p0], lr[v1][t1][p1] = s1, s0
                th0 = MH.ltl_trip_eval(lr[v0][t0], veh_cls[v0], inst)[2]
                th1 = MH.ltl_trip_eval(lr[v1][t1], veh_cls[v1], inst)[2]
                if (th0 <= P.NIGHT_HOURS and th1 <= P.NIGHT_HOURS
                        and MH.evaluate(ft, lr, inst) < MH.evaluate(ft, snap, inst) - 1e-9):
                    improved_any = True
                    break
                lr = snap
        # (d) 2-opt: 路线内段反转(首改进)
        for v in lr:
            for ti in range(len(lr[v])):
                r = lr[v][ti]
                done = False
                for a in range(len(r) - 1):
                    for b in range(a + 1, len(r)):
                        nr = r[:a] + r[a:b + 1][::-1] + r[b + 1:]
                        if MH.ltl_trip_eval(nr, veh_cls[v], inst)[2] > P.NIGHT_HOURS:
                            continue
                        c1 = MH.evaluate(ft, {**lr, v: lr[v][:ti] + [nr] + lr[v][ti + 1:]}, inst)
                        if c1 < MH.evaluate(ft, lr, inst) - 1e-9:
                            lr[v][ti] = nr; r = nr; improved_any = True; done = True
                            break
                    if done:
                        break
        # (e) FTL: 趟数 ±1(预算内且降本)
        for (v, fid) in list(ft.keys()):
            for dv in (-1, 1):
                cur = ft.get((v, fid), 0)
                if cur + dv < 0:
                    continue
                snap = dict(ft)
                if cur + dv == 0:
                    del ft[(v, fid)]
                else:
                    ft[(v, fid)] = cur + dv
                if v_time_all(ft, lr, inst, veh_cls)[v] <= budget + 1e-9 and \
                        MH.evaluate(ft, lr, inst) < MH.evaluate(snap, lr, inst) - 1e-9:
                    improved_any = True
                else:
                    ft = snap
    return ft, lr


def perturb(ft, lr, inst, rng, veh_cls):
    """随机拆 2-4 个已访问站点的全部访问, 逐站最优位贪心重建(未装完即留缺货)。"""
    all_sites = sorted({s for ts in lr.values() for t in ts if t for s in t})
    if not all_sites:
        return
    k = min(len(all_sites), rng.randint(2, 4))
    sites = set(rng.sample(all_sites, k))
    for v in list(lr):
        lr[v] = [[s for s in t if s not in sites] for t in lr[v] if t]
        lr[v] = [t for t in lr[v] if t]
    for s in sorted(sites):
        _try_insert_best(s, ft, lr, inst, veh_cls, accept_if_improves=False)


def run_ils(inst, seed=42, budget_s=None, max_iters=None):
    """budget_s=标定模式(墙钟停止, 记录周期数); max_iters=正式模式(固定周期, 逐位可复现)。"""
    rng = random.Random(seed)
    veh_cls = MF.get_veh_classes(inst)
    t0 = time.time()
    ft, lr = MH.construct(inst, rng)
    ft, lr = local_search(ft, lr, inst, veh_cls)
    best_ft, best_lr = copy.deepcopy(ft), snap_lr(lr)
    best_c = MH.evaluate(best_ft, best_lr, inst)
    n_iter = 0
    if max_iters is not None:
        for _ in range(max_iters):
            n_iter += 1
            ft2, lr2 = copy.deepcopy(best_ft), snap_lr(best_lr)
            perturb(ft2, lr2, inst, rng, veh_cls)
            ft2, lr2 = local_search(ft2, lr2, inst, veh_cls)
            c2 = MH.evaluate(ft2, lr2, inst)
            if c2 < best_c - 1e-9:
                best_ft, best_lr, best_c = ft2, lr2, c2
    else:
        while time.time() - t0 < budget_s:
            n_iter += 1
            ft2, lr2 = copy.deepcopy(best_ft), snap_lr(best_lr)
            perturb(ft2, lr2, inst, rng, veh_cls)
            ft2, lr2 = local_search(ft2, lr2, inst, veh_cls)
            c2 = MH.evaluate(ft2, lr2, inst)
            if c2 < best_c - 1e-9:
                best_ft, best_lr, best_c = ft2, lr2, c2
    return best_ft, best_lr, best_c, n_iter, time.time() - t0
