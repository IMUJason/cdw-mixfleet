# -*- coding: utf-8 -*-
"""正式规模研究(隔离): 小规模族 10 个 + 大规模族 10 个。只写 results/scale_study/。

协议(与用户确认的口径):
  小规模: 候选池 4 规模 x seed 1..4(筛查顺延替补), CPLEX 1800s 容差 0.5%;
          关上(closed<=0.5%)者入族, 按固定顺序取前 10; 关不上者自动降级不采用。
          SA/ILS: 60s 墙钟标定记录迭代/周期数 -> 固定数重跑(逐位可复现), reprice 口径,
          报 gap vs proven optimum —— "recover optimum" 经验验证。
  大规模: 候选池 5 规模 x seed 1..3(筛查顺延), CPLEX 3600s 容差 0.1%;
          取前 10 个(不论关上与否, 预期全关不上)。强化 LP 界(秒级)与 CPLEX 界取紧
          作为 best_lb; SA/ILS: 180s 标定->固定重跑, reprice; 报 gap vs incumbent
          与 certified gap vs best_lb。
断点续跑: 每族 CSV 一行=一个实例全部阶段完成; 重启时跳过已有行(丢的至多一个实例)。
"""
import os, sys, csv, time, copy, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pulp
import mixfleet_model as MF, mixfleet_heuristic as MH
import params as P
import reprice as RP
import gen_scale as GS
import ils as ILS  # 本目录同源副本(与复现包 cdw-mixfleet 的 ils.py 逐字一致)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUTDIR = os.path.join(ROOT, "results", "scale_study")
SMALL_CSV = os.path.join(OUTDIR, "scale_small.csv")
LARGE_CSV = os.path.join(OUTDIR, "scale_large.csv")
LOG = os.path.join(OUTDIR, "run_scale_study.log")

SMALL_CPX = dict(time_limit=1800, gap=0.005)
LARGE_CPX = dict(time_limit=3600, gap=0.001)
SA_BUDGET = {"small": 60, "large": 180}
N_PER_FAMILY = 10

SMALL_POOL = [("SA08", 3, 8), ("SA10", 3, 10), ("SB10", 4, 10), ("SB12", 4, 12)]
LARGE_POOL = [("LC16", 4, 16), ("LC20", 5, 20), ("LC24", 5, 24),
              ("LD30", 6, 30), ("LE32", 7, 32)]
SEED_SPAN = 5          # 每规模最多顺延到的 seed 上限(筛查替补用)


def log(msg):
    print(msg, flush=True)


def lp_bound(inst, cap=900):
    """强化公式的根 LP 下界(与论文 lp_gaps 协议一致)。"""
    m, _ = MF.build_mip(inst, solve=False, use_flow=True, use_mtz=True)
    for v in m.variables():
        v.cat = pulp.LpContinuous
    t0 = time.time()
    m.solve(P.get_solver(msg=0, timeLimit=cap))
    obj = pulp.value(m.objective) if m.status == pulp.LpStatusOptimal else None
    return obj, time.time() - t0


def run_sa_fixed(inst, budget_s, seed=42):
    """SA: 墙钟标定记录迭代数 -> 固定迭代重跑(论文协议)。"""
    _, _, _, hm = MH.solve(inst, time_limit=budget_s, seed=seed)
    iters = hm["iters"]
    t0 = time.time()
    ft, lr, hc, hm2 = MH.solve(inst, time_limit=budget_s * 3, seed=seed, max_iters=iters)
    wt = time.time() - t0
    rc, st = RP.reprice(inst, ft, lr)
    return (rc if rc is not None else hc), iters, wt, st


def run_ils_fixed(inst, budget_s, seed=42):
    """ILS: 墙钟标定记录周期数 -> 固定周期重跑(留 1 周期余量, 论文协议)。"""
    _, _, _, n_cal, _ = ILS.run_ils(inst, seed=seed, budget_s=budget_s)
    n_fix = max(1, n_cal - 1)
    ft, lr, c_eval, n_it, wt = ILS.run_ils(inst, seed=seed, max_iters=n_fix)
    rc, st = RP.reprice(inst, ft, lr)
    return (rc if rc is not None else c_eval), n_fix, wt, st


def _done_keys(path):
    """返回 (已完成实例键集合, 其中被接受[非降级]的数量) —— 降级行不占族内名额。"""
    keys = set()
    n_accepted = 0
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                keys.add((r["size_id"], int(r["seed"])))
                if str(r.get("demoted", "")).lower() not in ("true", "1"):
                    n_accepted += 1
    return keys, n_accepted


def _append(path, fields, row):
    first = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if first:
            w.writeheader()
        w.writerow(row)
        f.flush()


def candidates(pool):
    """固定顺序的候选流: 规模轮转(seed 1 of 各规模, 再 seed 2, ...), 保证族内规模多样。"""
    for seed in range(1, SEED_SPAN + 1):
        for size_id, nf, nl in pool:
            yield size_id, nf, nl, seed


def run_family(fam, pool, cpx_cfg, out_csv):
    if fam not in SA_BUDGET:
        sys.exit(f"unknown family {fam}")
    budget = SA_BUDGET[fam]
    fields = ["family", "size_id", "nf", "nl", "seed", "veh", "screen",
              "cpx_status", "cpx_incumbent", "cpx_bound", "cpx_gap_pct", "cpx_time_s",
              "closed", "lp_bound", "best_lb",
              "sa_reprice", "sa_iters", "sa_time_s", "sa_gap_inc_pct", "sa_gap_cert_pct",
              "ils_reprice", "ils_cycles", "ils_time_s", "ils_gap_inc_pct", "ils_gap_cert_pct",
              "sa_vs_ils_pct", "demoted"]
    done, n_ok = _done_keys(out_csv)
    for size_id, nf, nl, seed in candidates(pool):
        if n_ok >= N_PER_FAMILY:
            break
        if (size_id, seed) in done:
            continue
        inst = GS.gen_scale_instance(nf, nl, seed)
        ok, why, _ = GS.screen(inst)
        if not ok:
            log(f"[{fam}][{size_id} s{seed}] screen-rejected: {why}")
            continue
        veh = GS.desc(inst)
        log(f"[{fam}][{size_id} s{seed}] {veh} CPLEX {cpx_cfg['time_limit']}s ...")
        t0 = time.time()
        m, _ = MF.build_mip(inst, time_limit=cpx_cfg["time_limit"], gap=cpx_cfg["gap"])
        wt = time.time() - t0
        rep = MF.solver_report(m)
        closed = rep["mip_gap_pct"] is not None and rep["mip_gap_pct"] <= 0.5
        log(f"[{fam}][{size_id} s{seed}] CPLEX {rep['status']} inc={rep['incumbent']:.0f} "
            f"bnd={rep['bound']:.0f} gap={rep['mip_gap_pct']}% ({wt:.0f}s) closed={closed}")
        # 小规模且未关上 -> 降级跳过(不入族); 大规模照常入族
        if fam == "small" and not closed:
            _append(out_csv, fields, dict(family=fam, size_id=size_id, nf=nf, nl=nl, seed=seed,
                                          veh=veh, screen=True, cpx_status=rep["status"],
                                          cpx_incumbent=f"{rep['incumbent']:.0f}",
                                          cpx_bound=f"{rep['bound']:.0f}",
                                          cpx_gap_pct=rep["mip_gap_pct"],
                                          cpx_time_s=f"{wt:.0f}", closed=False,
                                          lp_bound="", best_lb="", sa_reprice="",
                                          sa_iters="", sa_time_s="", sa_gap_inc_pct="",
                                          sa_gap_cert_pct="", ils_reprice="", ils_cycles="",
                                          ils_time_s="", ils_gap_inc_pct="", ils_gap_cert_pct="",
                                          sa_vs_ils_pct="", demoted=True))
            log(f"[{fam}][{size_id} s{seed}] NOT closed -> demoted (recorded, not counted)")
            continue
        # LP 界 + best_lb
        lpb, lpb_t = lp_bound(inst)
        cpx_lb = rep["bound"] if rep["bound"] else 0.0
        best_lb = max(cpx_lb, lpb if lpb is not None else 0.0)
        log(f"[{fam}][{size_id} s{seed}] LP bound {lpb:.0f} ({lpb_t:.0f}s) | best_lb {best_lb:.0f}")
        # SA + ILS(标定->固定)
        sa_cost, sa_it, sa_wt, sa_st = run_sa_fixed(inst, budget)
        ils_cost, il_it, il_wt, il_st = run_ils_fixed(inst, budget)
        inc = rep["incumbent"]
        row = dict(family=fam, size_id=size_id, nf=nf, nl=nl, seed=seed, veh=veh, screen=True,
                   cpx_status=rep["status"], cpx_incumbent=f"{inc:.0f}",
                   cpx_bound=f"{rep['bound']:.0f}", cpx_gap_pct=rep["mip_gap_pct"],
                   cpx_time_s=f"{wt:.0f}", closed=closed,
                   lp_bound=f"{lpb:.0f}" if lpb is not None else "",
                   best_lb=f"{best_lb:.0f}",
                   sa_reprice=f"{sa_cost:.0f}", sa_iters=sa_it, sa_time_s=f"{sa_wt:.0f}",
                   sa_gap_inc_pct=f"{(sa_cost - inc) / inc * 100:.2f}",
                   sa_gap_cert_pct=f"{(sa_cost - best_lb) / best_lb * 100:.2f}",
                   ils_reprice=f"{ils_cost:.0f}", ils_cycles=il_it, ils_time_s=f"{il_wt:.0f}",
                   ils_gap_inc_pct=f"{(ils_cost - inc) / inc * 100:.2f}",
                   ils_gap_cert_pct=f"{(ils_cost - best_lb) / best_lb * 100:.2f}",
                   sa_vs_ils_pct=f"{(sa_cost - ils_cost) / ils_cost * 100:.2f}",
                   demoted=False)
        _append(out_csv, fields, row)
        n_ok += 1
        log(f"[{fam}][{size_id} s{seed}] SA {sa_cost:.0f} (gap_inc {row['sa_gap_inc_pct']}%, "
            f"cert {row['sa_gap_cert_pct']}%) | ILS {ils_cost:.0f} (gap_inc "
            f"{row['ils_gap_inc_pct']}%, cert {row['ils_gap_cert_pct']}%) -> accepted "
            f"({n_ok}/{N_PER_FAMILY})")
    log(f"[{fam}] family complete: {n_ok} accepted")


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    GS.calibrate_from_paper()
    run_family("small", SMALL_POOL, SMALL_CPX, SMALL_CSV)
    run_family("large", LARGE_POOL, LARGE_CPX, LARGE_CSV)
    log("ALL DONE")


if __name__ == "__main__":
    main()
