# -*- coding: utf-8 -*-
"""实例导入/导出: inst dict <-> 单个自包含 CSV(分节: meta/params/depot/ftl/ltl/sinks/fleet/distances)。
公开复现包用: 导出的 CSV 是算例的冻结真值(不依赖生成代码与路网文件)。
往返保证: load(export(inst)) 与原 inst 逐字段等价(D 矩阵数值一致)。"""
import csv
import params as P


def export_instance(inst, path, meta=None):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        m = dict(meta or {})
        m.update({"n_ftl": inst["n_ftl"], "n_ltl": inst["n_ltl"],
                  "n_vehicles": inst["n_vehicles"],
                  "trips_per_vehicle": inst.get("trips_per_vehicle", 8),
                  "fleet_budget_h": inst.get("fleet_budget", "")})
        w.writerow(["[meta]"]); w.writerow(["key", "value"])
        for k, v in m.items():
            w.writerow([k, v])
        # 求解时常数快照(透明起见; 求解仍读 params.py, 可被 CLI 覆盖)
        w.writerow([]); w.writerow(["[params]"])
        w.writerow(["W_t", P.TRUCK_CAP_T]); w.writerow(["night_h", P.NIGHT_HOURS])
        w.writerow(["F_trip_cny", P.TRIP_FIXED]); w.writerow(["c_km_cny", P.TRIP_PER_KM])
        w.writerow(["shortage_penalty_cny_per_t", P.SHORTAGE_PENALTY])
        w.writerow(["speed_kmh", 35.0]); w.writerow(["load_unload_h_per_fullload", P.LOAD_UNLOAD_H])
        # 节点
        w.writerow([]); w.writerow(["[depot]"]); w.writerow(["node_id", "lng", "lat"])
        w.writerow([0, inst["depot"]["loc"][0], inst["depot"]["loc"][1]])
        w.writerow([]); w.writerow(["[ftl_sites]"])
        w.writerow(["site_id", "class", "demand_t", "lng", "lat", "node_id"])
        for s in inst["ftl"]:
            w.writerow([s["id"], s["cls"], s["demand"], s["coord"][0], s["coord"][1],
                        inst["ftl_idx"][s["id"]]])
        w.writerow([]); w.writerow(["[ltl_sites]"])
        w.writerow(["site_id", "class", "demand_t", "lng", "lat", "node_id"])
        for s in inst["ltl"]:
            w.writerow([s["id"], s["cls"], s["demand"], s["coord"][0], s["coord"][1],
                        inst["ltl_idx"][s["id"]]])
        w.writerow([]); w.writerow(["[sinks]"])
        w.writerow(["sink_id", "type", "fee_cny_per_t", "revenue_cny_per_t", "lng", "lat", "node_id", "note"])
        for k in inst["sinks"]:
            w.writerow([k["id"], k["type"], k["fee"], k["revenue"],
                        k["coord"][0], k["coord"][1], inst["sink_idx"][k["id"]],
                        k.get("note", "")])
        w.writerow([]); w.writerow(["[fleet]"]); w.writerow(["vehicle_id", "class"])
        for v, c in enumerate(inst.get("veh_classes") or []):
            w.writerow([v, c])
        # 距离矩阵(含表头行/列 = node_id)
        w.writerow([]); w.writerow(["[distances_km]"])
        n = len(inst["D"])
        w.writerow(["node_id"] + list(range(n)))
        for i in range(n):
            w.writerow([i] + [inst["D"][i][j] for j in range(n)])


def _sec(rows):
    """把 (行列表) 切成 {节名: [数据行]} 字典。"""
    out, cur = {}, None
    for r in rows:
        if len(r) == 1 and r[0].startswith("[") and r[0].endswith("]"):
            cur = r[0][1:-1]; out[cur] = []
        elif cur is not None:
            out[cur].append(r)
    return out


def load_instance(path):
    with open(path, encoding="utf-8") as f:
        rows = [r for r in csv.reader(f) if r]
    sec = _sec(rows)
    meta = {r[0]: r[1] for r in sec["meta"] if r[0] != "key"}
    # 节点坐标表(node_id -> (lng, lat))
    coords = {int(r[0]): (float(r[1]), float(r[2])) for r in sec["depot"][1:]}
    ftl, ltl, sinks = [], [], []
    ftl_idx, ltl_idx, sink_idx = [], [], []
    for r in sec["ftl_sites"][1:]:
        ftl.append(dict(id=int(r[0]), cls=r[1], demand=float(r[2]),
                        coord=(float(r[3]), float(r[4]))))
        ftl_idx.append(int(r[5])); coords[int(r[5])] = (float(r[3]), float(r[4]))
    for r in sec["ltl_sites"][1:]:
        ltl.append(dict(id=int(r[0]), cls=r[1], demand=float(r[2]),
                        coord=(float(r[3]), float(r[4]))))
        ltl_idx.append(int(r[5])); coords[int(r[5])] = (float(r[3]), float(r[4]))
    for r in sec["sinks"][1:]:
        sinks.append(dict(id=int(r[0]), type=r[1], fee=float(r[2]), revenue=float(r[3]),
                          coord=(float(r[4]), float(r[5]))))
        sink_idx.append(int(r[6])); coords[int(r[6])] = (float(r[4]), float(r[5]))
    veh_classes = [r[1] for r in sec["fleet"][1:]]
    # 距离矩阵
    drows = sec["distances_km"][1:]
    n = len(drows)
    D = [[0.0] * n for _ in range(n)]
    for r in drows:
        i = int(r[0])
        for j in range(n):
            D[i][j] = float(r[j + 1])
    return dict(n_ftl=len(ftl), n_ltl=len(ltl), n_vehicles=len(veh_classes),
                seed=None, depot=dict(loc=coords[0]), ftl=ftl, ltl=ltl,
                veh_classes=veh_classes, fleet_budget=float(meta["fleet_budget_h"]),
                sinks=sinks, D=D, depot_idx=0, ftl_idx=ftl_idx, ltl_idx=ltl_idx,
                sink_idx=sink_idx, real=True, trips_per_vehicle=int(meta["trips_per_vehicle"]))
