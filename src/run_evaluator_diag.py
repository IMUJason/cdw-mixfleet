# -*- coding: utf-8 -*-
"""E4(R2.6): first-fit 评估器偏差诊断 — S/M 冻结候选法。
方法: SA 搜索中每隔 N 次迭代保存候选解(结构+first-fit 成本), 事后对每个候选
分别用 evaluate(first-fit) 和 reprice(结构固定 LP) 计算, 比较成本排序/接受翻转。
输出 results/tables/evaluator_diag.csv"""
import os, sys, csv, time, copy, random, math
sys.path.insert(0, os.path.dirname(__file__))
import params as P
import mixfleet_model as MF, mixfleet_heuristic as MH
import inst_config as CFG, reprice as RP
import run_mode_restricted as MR

TBL = os.path.join(CFG.ROOT, "results", "tables")
OUT = os.path.join(TBL, "evaluator_diag.csv")
SAMPLE_EVERY = 800       # 每 800 次迭代抽 1 个候选
TARGET_N = 200           # 目标候选数
TIME_LIMIT_PER_REPRICE = 5.0   # 每个 reprice 的墙钟上限(秒)


def collect_candidates(tag):
    """在 S/M 上跑 SA 并按固定间隔快照候选解。"""
    inst = MR.gen_inst(tag)
    rng = random.Random(42)
    veh_cls = MF.get_veh_classes(inst)
    ft, lr = MH.construct(inst, rng)
    cur_c = MH.evaluate(ft, lr, inst)
    ntr_max = inst.get("trips_per_vehicle", 5)
    _fb = inst.get("fleet_budget")
    budget = _fb if _fb is not None else P.NIGHT_HOURS * ntr_max
    siters = CFG.SA_ITERS.get(tag, 100000)
    cands = []
    it = 0
    T0 = max(1e-6, abs(cur_c) * 0.02); T = T0
    # 简化 SA 主循环(只做 insert + rar 两个最有效算子, 加快候选收集)
    while it < siters and len(cands) < TARGET_N:
        it += 1
        nft = copy.deepcopy(ft); nlr = copy.deepcopy(lr)
        # 简化: 随机做 drop + insert(模拟邻域移动)
        vs = [v for v in nlr if nlr[v]]
        if vs and rng.random() < 0.5:
            v = rng.choice(vs); trips = [t for t in nlr[v] if t]
            if trips:
                ti = rng.randrange(len(trips))
                if trips[ti]:
                    trips[ti].pop(rng.randrange(len(trips[ti])))
                    nlr[v] = [t for t in nlr[v] if t]
        else:
            # insert: 从剩余需求站点选一个插入
            remaining = MH._ltl_remaining(nlr, inst)
            cands_l = [lid for lid, r in remaining.items() if r > 0.01]
            if cands_l:
                s = rng.choice(cands_l)
                ltl_cls = {l["id"]: l["cls"] for l in inst["ltl"]}
                vs2 = [v for v in nlr if veh_cls[v] == ltl_cls[s]]
                if vs2:
                    v = rng.choice(vs2)
                    pos = [(ti, p) for ti in range(len(nlr[v]))
                           for p in range(len(nlr[v][ti]) + 1) if s not in nlr[v][ti]]
                    if pos:
                        ti, p = rng.choice(pos)
                        nr = nlr[v][ti][:p] + [s] + nlr[v][ti][p:]
                        _, _, th = MH.ltl_trip_eval(nr, veh_cls[v], inst)
                        if th <= P.NIGHT_HOURS:
                            nlr[v][ti] = nr
        c_new = MH.evaluate(nft, nlr, inst)
        d = c_new - cur_c
        if d < 0 or rng.random() < math.exp(-max(0, d) / max(T, 1e-9)):
            ft, lr, cur_c = nft, nlr, c_new
        T *= 0.99985
        if T < 1e-3 * T0:
            ft, lr = copy.deepcopy(ft), copy.deepcopy(lr)  # 保持
            T = 0.5 * T0
        if it % SAMPLE_EVERY == 0:
            cands.append((copy.deepcopy(ft), copy.deepcopy(lr), c_new))
    return inst, cands


def main():
    all_rows = []
    for tag in ("S", "M"):
        print(f"=== {tag}: collecting {TARGET_N} candidates ===", flush=True)
        inst, cands = collect_candidates(tag)
        print(f"  collected {len(cands)} candidates", flush=True)
        ff_costs, ex_costs = [], []
        for i, (ft, lr, ff_c) in enumerate(cands):
            t0 = time.time()
            try:
                rc, st = RP.reprice(inst, ft, lr)
            except Exception:
                rc, st = None, "Timeout"
            if rc is not None:
                ff_costs.append(ff_c)
                ex_costs.append(rc)
                all_rows.append(dict(instance=tag, cand_idx=i, first_fit=ff_c,
                                     exact=rc, diff=rc - ff_c,
                                     diff_pct=100.0 * (rc - ff_c) / ff_c if ff_c else 0))
                if i % 20 == 0:
                    print(f"  cand {i}: ff {ff_c:.0f} exact {rc:.0f} diff {rc-ff_c:+.1f} ({100*(rc-ff_c)/ff_c:+.2f}%)", flush=True)
        # 统计
        if len(ff_costs) > 1:
            diffs = [e - f for f, e in zip(ff_costs, ex_costs)]
            import statistics
            # Spearman rank correlation
            ff_rank = {v: i for i, v in enumerate(sorted(range(len(ff_costs)), key=lambda k: ff_costs[k]))}
            ex_rank = {v: i for i, v in enumerate(sorted(range(len(ex_costs)), key=lambda k: ex_costs[k]))}
            n = len(ff_costs)
            d2 = sum((ff_rank[i] - ex_rank[i]) ** 2 for i in range(n))
            rho = 1 - 6 * d2 / (n * (n * n - 1)) if n > 1 else 1.0
            print(f"\n{tag} summary: n={n} | mean diff {statistics.mean(diffs):+.2f} "
                  f"({100*statistics.mean(diffs)/statistics.mean(ff_costs):+.3f}%) | "
                  f"min {min(diffs):+.2f} max {max(diffs):+.2f} | "
                  f"Spearman rho {rho:.4f} | "
                  f"zero-diff rate {sum(1 for d in diffs if abs(d)<0.5)/len(diffs):.2%}", flush=True)
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        if all_rows:
            w = csv.DictWriter(fh, fieldnames=list(all_rows[0].keys()))
            w.writeheader(); w.writerows(all_rows)
    print("saved ->", OUT, flush=True)


if __name__ == "__main__":
    main()
