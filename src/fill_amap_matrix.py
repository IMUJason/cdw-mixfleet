"""补全 dongsheng_real_network.json 驾车矩阵的 None 单元。
优先高德 API 实测; 失败格用 直线×1.30(城市绕行系数) 估算并标记 est=true。"""
import os, sys, json, time, urllib.request, urllib.parse
sys.path.insert(0, os.path.dirname(__file__))
from mixfleet_model import haversine_km

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NET = os.path.join(ROOT, "data", "external", "dongsheng_real_network.json")
try:
    KEY = open(os.path.join(ROOT, "data", "external", ".amap_key")).read().strip()
except FileNotFoundError:
    KEY = None
    import sys as _sys
    print("[amap] no key at data/external/.amap_key - re-querying is unavailable; "
          "the frozen matrix/network JSON in data/external/ needs no key.", file=_sys.stderr)


def amap_distance(origin, dest):
    q = urllib.parse.urlencode(dict(origins=origin, destination=dest, type="1", key=KEY))
    for _ in range(3):
        try:
            r = json.load(urllib.request.urlopen("https://restapi.amap.com/v3/distance?" + q, timeout=25))
            res = r.get("results") or []
            if res and res[0].get("distance"):
                return float(res[0]["distance"]) / 1000.0, float(res[0]["duration"]) / 3600.0
        except Exception:
            time.sleep(1.5)
    return None, None


def main():
    net = json.load(open(NET, encoding="utf-8"))
    nodes, m = net["nodes"], net["matrix"]
    todo = [(i, j) for i in range(len(m)) for j in range(len(m)) if m[i][j] is None]
    print(f"filling {len(todo)} None cells...", flush=True)
    n_api = 0
    for k, (i, j) in enumerate(todo):
        o, d = nodes[i]["loc"], nodes[j]["loc"]
        dist, dur = amap_distance(o, d)
        if dist is not None:
            m[i][j] = dict(dist_km=round(dist, 2), dur_h=round(dur, 3))
            n_api += 1
        else:
            a = [float(x) for x in o.split(",")]
            b = [float(x) for x in d.split(",")]
            dd = haversine_km(a[0], a[1], b[0], b[1]) * 1.30
            m[i][j] = dict(dist_km=round(dd, 2), dur_h=round(dd / 35.0, 3), est=True)
        time.sleep(0.12)
        if (k + 1) % 10 == 0:
            print(f"  {k+1}/{len(todo)}", flush=True)
    net["matrix_fill_note"] = f"{n_api}/{len(todo)} cells via Amap API on fill run; rest estimated (hav*1.30, est=true)"
    json.dump(net, open(NET, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    left = sum(1 for row in m for c in row if c is None)
    est = sum(1 for row in m for c in row if c and c.get("est"))
    print(f"done: {n_api} API-filled, {est} estimated, {left} still None")


if __name__ == "__main__":
    main()
