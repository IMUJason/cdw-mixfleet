# -*- coding: utf-8 -*-
"""调度方案的保存/读取(公开包内通用格式)。
[result] 节: 求解方法/成本/状态等键值; [ftl_trips]: vehicle,site,n; [ltl_routes]: vehicle,slot,seq("3|5|0")。"""
import csv


def save_plan(path, ftl_ntrip, ltl_routes, result_meta):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["[result]"]); w.writerow(["key", "value"])
        for k, v in result_meta.items():
            w.writerow([k, v])
        w.writerow([]); w.writerow(["[ftl_trips]"]); w.writerow(["vehicle_id", "site_id", "n_trips"])
        for (v, fid), n in sorted(ftl_ntrip.items()):
            if n > 0:
                w.writerow([v, fid, n])
        w.writerow([]); w.writerow(["[ltl_routes]"]); w.writerow(["vehicle_id", "slot", "site_sequence"])
        for v, trips in ltl_routes.items():
            for t, r in enumerate(trips):
                if r:
                    w.writerow([v, t, "|".join(str(s) for s in r)])


def load_plan(path):
    with open(path, encoding="utf-8") as f:
        rows = [r for r in csv.reader(f) if r]
    sec, cur = {}, None
    for r in rows:
        if len(r) == 1 and r[0].startswith("["):
            cur = r[0][1:-1]; sec[cur] = []
        elif cur:
            sec[cur].append(r)
    meta = {r[0]: r[1] for r in sec.get("result", []) if r[0] != "key"}
    ftl = {}
    for r in sec.get("ftl_trips", [])[1:]:
        ftl[(int(r[0]), int(r[1]))] = int(r[2])
    ltl = {}
    for r in sec.get("ltl_routes", [])[1:]:
        v = int(r[0])
        seq = [int(x) for x in r[2].split("|")] if r[2] else []
        ltl.setdefault(v, []).append(seq)
    return meta, ftl, ltl
