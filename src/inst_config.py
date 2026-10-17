"""单夜口径实例配置(全量重跑共用): 读取 calibration_proposal.csv 的类别车队,
统一 trips_per_vehicle=R(变量空间装置)与 fleet_budget=当前 P.NIGHT_HOURS(调用时读取,
使 H 敏感性自动联动窗与预算)。"""
import os, csv
import params as P
import mixfleet_model as MF

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAL = os.path.join(ROOT, "results", "tables", "calibration_proposal.csv")
R = 8
CLASSES = list(P.CLASSES)
SA_TIME = {"S": 30, "M": 60, "L": 90, "X": 120}
CPLEX_LIMIT = {"S": 300, "M": 900, "L": 1200, "X": 1800}
GAP_TOL = 1e-3
SEEDS = [42, 7, 13, 99, 2024]


def _bench_iters():
    """SA 固定迭代预算: 以 mixfleet_bench.csv 记录的 heu_iters 为准(单一事实源),
    使所有 SA 重跑逐位一致, 不再依赖墙钟/机器负载(消除跨表数字漂移)。"""
    path = os.path.join(ROOT, "results", "tables", "mixfleet_bench.csv")
    out = {}
    try:
        with open(path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                out[r["instance"].split(":")[0]] = int(float(r["heu_iters"]))
    except Exception:
        pass
    return out


SA_ITERS = _bench_iters()


def _load():
    rows = {}
    with open(CAL, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows[r["tag"]] = r
    return rows


_ROWS = _load()


def fleet(tag):
    r = _ROWS[tag]
    return dict(nf=int(r["nf"]), nl=int(r["nl"]),
                counts={"earth": int(r["n_earth"]), "demolition": int(r["n_demol"]),
                        "renovation": int(r["n_renovation"])})


def gen(tag, seed):
    """按标定配置生成单夜实例(预算=调用时的 P.NIGHT_HOURS)。"""
    f = fleet(tag)
    vc = []
    for c in CLASSES:
        vc += [c] * f["counts"][c]
    return MF.gen_instance(f["nf"], f["nl"], len(vc), seed=seed, use_real_net=True,
                           trips_per_vehicle=R, veh_classes=vc,
                           fleet_budget=float(P.NIGHT_HOURS))


def desc(tag):
    f = fleet(tag)
    c = f["counts"]
    return (f"{tag}: {f['nf']}F+{f['nl']}L/{sum(c.values())}v "
            f"({c['earth']}e+{c['demolition']}d+{c['renovation']}r)")
