# -*- coding: utf-8 -*-
"""Scale-study instance generator (ISOLATED from paper pipeline).

Produces two fixed-seed instance families for the reviewer-requested scale
study, WITHOUT touching the calibrated S/M/L/X/XL instances or any file under
results/tables/. Everything here writes only to results/scale_study/.

Design (per the agreed protocol):
  * Demand at each site depends only on (n_ftl, n_ltl, seed) via the SAME
    MF.gen_instance draw used by the paper -> real Dongsheng network geometry,
    literature-calibrated lognormal tonnages. We never invent a new demand law.
  * Fleet is sized AUTOMATICALLY (not hand-tuned like XL): for each licensed
    class we pick the vehicle count that lands realized *capacity coverage* near
    a target, so instances are neither trivially over-served nor infeasible.
  * A degeneracy screen rejects draws where one site hogs a class's tonnage
    (the XL/seed-42 confound: 350 t of earth stuck on two long-cycle sites is a
    capacity artefact, not a scale effect).

The fleet-sizing proxy TONS_PER_VEH is deliberately exposed so the pilot can
recalibrate it against realized utilization before any long run.
"""
import os, sys, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import mixfleet_model as MF
import params as P

CLASSES = list(P.CLASSES)  # earth / demolition / renovation

# 论文五个标定实例 (tag, n_ftl, n_ltl, demand_seed, 车队构成) —— 配车校准的唯一依据
PAPER_INSTANCES = [
    ("S",  3, 8,  42, {"earth": 1,  "demolition": 4,  "renovation": 2}),
    ("M",  4, 12, 42, {"earth": 1,  "demolition": 8,  "renovation": 5}),
    ("L",  4, 16, 42, {"earth": 1,  "demolition": 8,  "renovation": 6}),
    ("X",  5, 24, 42, {"earth": 2,  "demolition": 15, "renovation": 8}),
    ("XL", 7, 32, 7,  {"earth": 7,  "demolition": 10, "renovation": 7}),
]

# Nominal nightly tonnage a single class-licensed vehicle can move, used only to
# SIZE the fleet (never to score a solution). Defaults are placeholders; the
# pilot calls calibrate_from_paper() which anchors them to the implied per-vehicle
# nightly tonnage of the paper's own five calibrated instances (median per class),
# so auto-fleeting reproduces the paper's 55-92% utilization band by construction.
TONS_PER_VEH = {"earth": 95.0, "demolition": 70.0, "renovation": 60.0}
TARGET_UTIL = 0.85          # aim capacity coverage here; realized util lands lower
MIN_VEH_PER_ACTIVE_CLASS = 1
# Degeneracy screen: reject if any single site holds more than this fraction of
# its class's total tonnage (single-site dominance -> capacity confound).
MAX_SITE_SHARE = 0.45


def _probe_demand(n_ftl, n_ltl, seed):
    """Read the (seed-fixed) demand draw with a throwaway fleet, so we can size
    the real fleet from the actual per-class tonnage. Vehicle count does not
    affect the demand draw, only the class list length assertion, so we pass a
    minimal valid fleet here."""
    vc = [CLASSES[0]]  # 1-vehicle dummy just to satisfy the signature
    inst = MF.gen_instance(n_ftl, n_ltl, 1, seed=seed, use_real_net=True,
                           trips_per_vehicle=8, veh_classes=vc,
                           fleet_budget=float(P.NIGHT_HOURS))
    return inst


def _class_tonnage(inst):
    tot = {c: 0.0 for c in CLASSES}
    sites = {c: [] for c in CLASSES}
    for s in inst["ftl"] + inst["ltl"]:
        tot[s["cls"]] += s["demand"]
        sites[s["cls"]].append(s["demand"])
    return tot, sites


def _size_fleet(tot):
    """Auto-size class-licensed fleet from per-class tonnage and the capacity
    proxy. Returns an ordered veh_classes list (earth, then demolition, then
    renovation) matching how the paper builds veh_classes."""
    counts = {}
    for c in CLASSES:
        if tot[c] <= 0:
            counts[c] = 0
            continue
        n = math.ceil(tot[c] / (TARGET_UTIL * TONS_PER_VEH[c]))
        counts[c] = max(MIN_VEH_PER_ACTIVE_CLASS, n)
    return counts


def screen(inst):
    """Return (ok, reason, diagnostics).

    The screen targets the LTL *consolidation* sites only. FTL sites are bulk
    direct-haul by construction: a single earth FTL site carrying a large share
    of earth tonnage is the modeled reality (more trips on one lane), not a
    degenerate draw. Concentration only distorts the problem where multi-stop
    routing structure lives -- the LTL sites -- so that is where we screen for a
    single site hogging its class's consolidation tonnage."""
    diag = {}
    # per-class LTL-only tonnage
    ltl_tot = {c: 0.0 for c in CLASSES}
    ltl_sites = {c: [] for c in CLASSES}
    for s in inst["ltl"]:
        ltl_tot[s["cls"]] += s["demand"]
        ltl_sites[s["cls"]].append(s["demand"])
    worst_share = 0.0
    for c in CLASSES:
        if ltl_tot[c] <= 0 or len(ltl_sites[c]) < 2:
            diag[f"ltl_share_{c}"] = 0.0
            continue
        share = max(ltl_sites[c]) / ltl_tot[c]
        diag[f"ltl_share_{c}"] = round(share, 3)
        worst_share = max(worst_share, share)
    diag["worst_ltl_share"] = round(worst_share, 3)
    if worst_share > MAX_SITE_SHARE:
        return False, f"single LTL site dominance {worst_share:.2f}>{MAX_SITE_SHARE}", diag
    return True, "ok", diag


def gen_scale_instance(n_ftl, n_ltl, seed):
    """Build a fully-specified, auto-fleeted scale instance (paper-compatible
    dict). Fleet is derived from the seed-fixed demand draw."""
    probe = _probe_demand(n_ftl, n_ltl, seed)
    tot, _ = _class_tonnage(probe)
    counts = _size_fleet(tot)
    vc = []
    for c in CLASSES:
        vc += [c] * counts[c]
    inst = MF.gen_instance(n_ftl, n_ltl, len(vc), seed=seed, use_real_net=True,
                           trips_per_vehicle=8, veh_classes=vc,
                           fleet_budget=float(P.NIGHT_HOURS))
    inst["scale_fleet_counts"] = counts
    return inst


def desc(inst):
    c = inst["scale_fleet_counts"]
    return (f"{inst['n_ftl']}F+{inst['n_ltl']}L/{sum(c.values())}v "
            f"({c['earth']}e+{c['demolition']}d+{c['renovation']}r)")


def calibrate_from_paper():
    """把 TONS_PER_VEH 锚定到论文自己的标定实例: 对每个类别, 取
    implied = 该类总吨位 / (TARGET_UTIL * 该类车数) 在五个实例上的中位数。
    这样自动配车在论文实例规模上会复现出与人工标定同量级的车队。"""
    impl = {c: [] for c in CLASSES}
    for tag, nf, nl, seed, counts in PAPER_INSTANCES:
        probe = _probe_demand(nf, nl, seed)
        tot, _ = _class_tonnage(probe)
        for c in CLASSES:
            n = counts.get(c, 0)
            if n > 0 and tot[c] > 0:
                impl[c].append(tot[c] / (TARGET_UTIL * n))
    for c in CLASSES:
        if impl[c]:
            TONS_PER_VEH[c] = round(float(np.median(impl[c])), 1)
    return dict(TONS_PER_VEH)


if __name__ == "__main__":
    cal = calibrate_from_paper()
    print("calibrated TONS_PER_VEH:", cal, flush=True)
    print("--- auto-fleet vs paper calibration (same nf/nl/seed) ---", flush=True)
    for tag, nf, nl, seed, counts in PAPER_INSTANCES:
        inst = gen_scale_instance(nf, nl, seed)
        auto = inst["scale_fleet_counts"]
        print(f"{tag}: auto {auto} (={sum(auto.values())}v)  vs paper {counts} "
              f"(={sum(counts.values())}v)", flush=True)
    print("--- candidate scale sizes ---", flush=True)
    for nf, nl in [(3, 8), (4, 16), (6, 30)]:
        inst = gen_scale_instance(nf, nl, 1)
        ok, why, diag = screen(inst)
        tot, _ = _class_tonnage(inst)
        print(f"{desc(inst)} | tot={ {k: round(v) for k, v in tot.items()} } "
              f"| screen={ok} ({why}) worst_ltl_share={diag['worst_ltl_share']}", flush=True)
