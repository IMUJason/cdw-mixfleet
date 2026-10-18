# -*- coding: utf-8 -*-
"""小规模族两阶段补齐(用户策略: 快速抽样舍弃 + 并行筛 + 赢家串行精测)。

阶段一 screen: 候选抽样 6 进程 x 3 线程并行, 每例 CPLEX 上限 SCREEN_T=300s
  (历史已关实例用时 5-159s 的 ~2 倍), 容差 0.5% —— 到点即停: 关上=保留, 没关上=舍弃。
  筛满 NEED 个保留即止。结果记 screen_small.csv。
阶段二 serial: 保留者逐个串行精测(默认全线程, 与大规模族计时口径一致):
  CPLEX 3600s 容差 0.5%(即停) + LP 界 + SA/ILS(60s 标定->固定) 完整管线,
  官方数字落 scale_small_final.csv(先并入 v2 已接受的 4 行, 共 10 行)。
"""
import os, sys, csv, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from concurrent.futures import ProcessPoolExecutor, as_completed

OUTDIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                      "results", "scale_study")
V2_CSV = os.path.join(OUTDIR, "scale_small_v2.csv")
SCREEN_CSV = os.path.join(OUTDIR, "screen_small.csv")
FINAL_CSV = os.path.join(OUTDIR, "scale_small_final.csv")

SCREEN_T = 300          # 快筛上限(已关实例历史用时上限 159s 的 ~2 倍)
GAP_TOL = 0.005
N_WORKERS = 6
WORKER_THREADS = 3
NEED = 6                # 还差的保留数(v2 已有 4 个接受)

EXT_POOL = [("SE09", 3, 9), ("SE11", 3, 11), ("SF11", 4, 11), ("SF13", 4, 13),
            ("SG08", 2, 8), ("SG09", 2, 9), ("SG10", 2, 10), ("SH07", 3, 7)]
SAME_EXTRA = [("SA08", 3, 8), ("SA10", 3, 10), ("SB10", 4, 10), ("SB12", 4, 12)]
SEED_SPAN_EXT = 14
EXTRA_SEED_START = 6

FIELDS = ["family", "size_id", "nf", "nl", "seed", "veh", "screen",
          "cpx_status", "cpx_incumbent", "cpx_bound", "cpx_gap_pct", "cpx_time_s",
          "closed", "lp_bound", "best_lb",
          "sa_reprice", "sa_iters", "sa_time_s", "sa_gap_inc_pct", "sa_gap_cert_pct",
          "ils_reprice", "ils_cycles", "ils_time_s", "ils_gap_inc_pct", "ils_gap_cert_pct",
          "sa_vs_ils_pct", "demoted"]


def log(m):
    print(m, flush=True)


def _init():
    """每个 worker 进程初始化一次: 校准配车系数。"""
    import gen_scale as GS
    GS.calibrate_from_paper()


def screen_one(job):
    """worker: 生成实例 -> LTL 筛查 -> CPLEX 快解(限核限时限容差)。"""
    size_id, nf, nl, seed = job
    import gen_scale as GS
    import mixfleet_model as MF
    import params as P
    import pulp
    inst = GS.gen_scale_instance(nf, nl, seed)
    ok, why, _ = GS.screen(inst)
    if not ok:
        return dict(size_id=size_id, nf=nf, nl=nl, seed=seed, veh=GS.desc(inst),
                    kept=False, note=f"rejected:{why}")
    m, _ = MF.build_mip(inst, solve=False)
    t0 = time.time()
    m.solve(P.get_solver(msg=0, timeLimit=SCREEN_T, gapRel=GAP_TOL, threads=WORKER_THREADS))
    wt = time.time() - t0
    rep = MF.solver_report(m)
    closed = rep["mip_gap_pct"] is not None and rep["mip_gap_pct"] <= 0.5
    return dict(size_id=size_id, nf=nf, nl=nl, seed=seed, veh=GS.desc(inst),
                kept=bool(closed), note="",
                status=rep["status"],
                incumbent=rep["incumbent"], bound=rep["bound"],
                gap_pct=rep["mip_gap_pct"], time_s=round(wt))


def build_stream():
    """候选流(与 complete_small 一致), 剔除 v2 已有结果与已筛过的(screen_small.csv)实例。"""
    done = set()
    if os.path.exists(V2_CSV):
        with open(V2_CSV, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                done.add((r["size_id"], int(r["seed"])))
    if os.path.exists(SCREEN_CSV):
        with open(SCREEN_CSV, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                done.add((r["size_id"], int(r["seed"])))
    stream = []
    for seed in range(1, SEED_SPAN_EXT + 1):
        for size_id, nf, nl in EXT_POOL:
            stream.append((size_id, nf, nl, seed))
        if seed >= EXTRA_SEED_START:
            for size_id, nf, nl in SAME_EXTRA:
                stream.append((size_id, nf, nl, seed))
    return [s for s in stream if (s[0], s[3]) not in done]


def prior_keepers():
    """往轮筛出但尚未进入 FINAL 的保留者(断点恢复用)。"""
    out, done_final = [], set()
    if os.path.exists(FINAL_CSV):
        with open(FINAL_CSV, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                done_final.add((r["size_id"], int(r["seed"])))
    if os.path.exists(SCREEN_CSV):
        with open(SCREEN_CSV, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if str(r.get("kept", "")).lower() == "true":
                    key = (r["size_id"], int(r["nf"]), int(r["nl"]), int(r["seed"]))
                    if (r["size_id"], int(r["seed"])) not in done_final:
                        out.append(key)
    return out


def main():
    # ---------- 阶段一: 并行快筛 ----------
    stream = build_stream()
    prior = prior_keepers()
    need_new = max(0, NEED - len(prior))          # 断点恢复: 只补差额, 不超采
    log(f"phase 1: parallel screening, {len(stream)} candidates, "
        f"cap {SCREEN_T}s x {WORKER_THREADS} threads, prior keepers {len(prior)}, "
        f"need {need_new} more")
    keepers, tried = [], 0
    scr_f = open(SCREEN_CSV, "a", newline="", encoding="utf-8-sig")
    scr_w = csv.DictWriter(scr_f, fieldnames=["size_id", "nf", "nl", "seed", "veh",
                                              "kept", "note", "status", "incumbent",
                                              "bound", "gap_pct", "time_s"])
    if os.path.getsize(SCREEN_CSV) == 0 or sum(1 for _ in open(SCREEN_CSV, encoding="utf-8-sig")) < 2:
        scr_w.writeheader()
    i = 0
    with ProcessPoolExecutor(max_workers=N_WORKERS, initializer=_init) as ex:
        while i < len(stream) and len(keepers) < need_new:
            batch = stream[i:i + N_WORKERS * 2]      # 每轮提交 2 倍于工人数
            i += len(batch)
            futs = {ex.submit(screen_one, j): j for j in batch}
            for fut in as_completed(futs):
                r = fut.result()
                tried += 1
                scr_w.writerow({k: r.get(k, "") for k in
                                ["size_id", "nf", "nl", "seed", "veh", "kept", "note",
                                 "status", "incumbent", "bound", "gap_pct", "time_s"]})
                scr_f.flush()
                if r["kept"]:
                    keepers.append((r["size_id"], r["nf"], r["nl"], r["seed"]))
                    log(f"  KEEP {r['size_id']}-s{r['seed']} {r['veh']} gap={r['gap_pct']}% "
                        f"({r['time_s']}s) -> {len(keepers)}/{need_new}")
                elif r["note"]:
                    log(f"  drop {r['size_id']}-s{r['seed']} ({r['note']})")
                else:
                    log(f"  drop {r['size_id']}-s{r['seed']} gap={r['gap_pct']}% ({r['time_s']}s)")
                if len(keepers) >= need_new:
                    for f2 in futs:
                        f2.cancel()
                    break
    scr_f.close()
    # 合并往轮保留者(断点恢复): 本轮新筛出的 + screen CSV 里已保留但未进 FINAL 的
    seen = {(k[0], k[3]) for k in keepers}
    for k in prior_keepers():
        if (k[0], k[3]) not in seen:
            keepers.append(k)
            seen.add((k[0], k[3]))
    log(f"phase 1 done: tried {tried} this session; keepers total {len(keepers)}/{NEED}: {keepers}")
    if len(keepers) < NEED:
        log("NOT ENOUGH KEEPERS - extend pool and rerun (resume-safe)")
        return

    # ---------- 阶段二: 赢家串行精测 ----------
    import gen_scale as GS
    import mixfleet_model as MF
    from run_scale_study import run_sa_fixed, run_ils_fixed, lp_bound, SA_BUDGET, _append
    GS.calibrate_from_paper()
    if not os.path.exists(FINAL_CSV):
        n_seeded = 0
        if os.path.exists(V2_CSV):
            with open(V2_CSV, encoding="utf-8-sig") as f:
                for r in csv.DictReader(f):
                    if str(r.get("demoted", "")).lower() not in ("true", "1"):
                        _append(FINAL_CSV, FIELDS, r)
                        n_seeded += 1
        log(f"phase 2: seeded {n_seeded} accepted rows from v2")
    for size_id, nf, nl, seed in keepers:
        inst = GS.gen_scale_instance(nf, nl, seed)
        veh = GS.desc(inst)
        log(f"[serial][{size_id} s{seed}] {veh} CPLEX 3600s ...")
        t0 = time.time()
        m, _ = MF.build_mip(inst, time_limit=3600, gap=GAP_TOL)
        wt = time.time() - t0
        rep = MF.solver_report(m)
        closed = rep["mip_gap_pct"] is not None and rep["mip_gap_pct"] <= 0.5
        log(f"[serial][{size_id} s{seed}] {rep['status']} inc={rep['incumbent']:.0f} "
            f"bnd={rep['bound']:.0f} gap={rep['mip_gap_pct']}% ({wt:.0f}s) closed={closed}")
        if not closed:
            log(f"[serial][{size_id} s{seed}] WARNING: did not close in serial rerun "
                f"(screening said closed) - skipped, take next candidate instead")
            continue
        lpb, _ = lp_bound(inst)
        cpx_lb = rep["bound"] if rep["bound"] else 0.0
        best_lb = max(cpx_lb, lpb if lpb is not None else 0.0)
        sa_cost, sa_it, sa_wt, _ = run_sa_fixed(inst, SA_BUDGET["small"])
        ils_cost, il_it, il_wt, _ = run_ils_fixed(inst, SA_BUDGET["small"])
        inc = rep["incumbent"]
        row = dict(family="small", size_id=size_id, nf=nf, nl=nl, seed=seed, veh=veh,
                   screen=True, cpx_status=rep["status"], cpx_incumbent=f"{inc:.0f}",
                   cpx_bound=f"{rep['bound']:.0f}", cpx_gap_pct=rep["mip_gap_pct"],
                   cpx_time_s=f"{wt:.0f}", closed=True,
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
        _append(FINAL_CSV, FIELDS, row)
        log(f"[serial][{size_id} s{seed}] SA {sa_cost:.0f} (inc {row['sa_gap_inc_pct']}%) | "
            f"ILS {ils_cost:.0f} (inc {row['ils_gap_inc_pct']}%) -> recorded")
    log("ALL DONE")


if __name__ == "__main__":
    main()
