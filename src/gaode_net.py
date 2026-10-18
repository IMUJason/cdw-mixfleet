"""高德 API 构建东胜区真实路网算例。
1) POI 搜索真实 CDW 设施(建筑垃圾/渣土/消纳/资源化/中转) + 真实街道/镇做产生区
2) 地理编码得坐标; 3) 驾车距离/时间矩阵(真实, 非欧氏); 4) 缓存到 data/external/。
输出 data/processed/instance_real_dongsheng.json(CDW-MDCA 实例, 注入真实距离)。"""
import os, sys, json, time, urllib.request, urllib.parse
sys.path.insert(0, os.path.dirname(__file__))
import params as P
import instance_gen as ig

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY = open(os.path.join(ROOT, "data", "external", ".amap_key")).read().strip()
CITY = "鄂尔多斯"; ADCODE = "150602"  # 东胜区
CACHE = os.path.join(ROOT, "data", "external", "dongsheng_real_network.json")

def _get(url, params):
    q = urllib.parse.urlencode({**params, "key": KEY})
    for _ in range(3):
        try:
            return json.load(urllib.request.urlopen(url + "?" + q, timeout=25))
        except Exception:
            time.sleep(1.5)
    return {}

def poi_search(kw, types="", n=8):
    r = _get("https://restapi.amap.com/v3/place/text",
             dict(keywords=kw, city=ADCODE, citylimit="true", types=types, offset=n, page=1))
    return [(p["name"], p["location"]) for p in r.get("pois", []) if p.get("location")]

def geocode(addr):
    r = _get("https://restapi.amap.com/v3/geocode/geo", dict(address=addr, city=CITY))
    gc = r.get("geocodes") or []
    return gc[0]["location"] if gc else None

def distance(origins, dest):
    # origins: "lon,lat;lon,lat;..." dest: "lon,lat"  type=1 驾车
    r = _get("https://restapi.amap.com/v3/distance", dict(origins=origins, destination=dest, type="1"))
    return [(it.get("distance"), it.get("duration")) for it in (r.get("results") or [])]

def classify(name):
    n = name
    if any(k in n for k in ["综合处理", "资源化", "资源", "再生", "处理厂", "破碎"]): return "resource"
    if any(k in n for k in ["消纳", "填埋", "弃土场", "渣土场"]): return "landfill"
    if any(k in n for k in ["中转", "转运"]): return "transfer"
    if any(k in n for k in ["回填", "填筑", "平整"]): return "backfill"
    return None

def build_real_network():
    if os.path.exists(CACHE):
        return json.load(open(CACHE, encoding="utf-8"))
    # 1) POI 搜真实设施
    facilities = {}  # (type,name,loc)
    for kw in ["建筑垃圾处理", "建筑垃圾消纳", "渣土消纳", "建筑垃圾中转", "建筑垃圾资源化", "再生资源"]:
        for name, loc in poi_search(kw):
            t = classify(name)
            if t and t not in [f["type"] for f in facilities.values()]:
                facilities[len(facilities)] = dict(name=name, loc=loc, type=t)
        time.sleep(0.3)
    # 补: 用已知真实设施名 geocode(POI 搜不到时)
    known = [("东胜区建筑垃圾综合处理中心", "resource"), ("金辰建筑垃圾处理厂", "resource"),
             ("东胜区北郊建筑垃圾消纳场", "landfill")]
    seen_types = set(f["type"] for f in facilities.values())
    for name, t in known:
        if t in seen_types and any(t == f["type"] for f in facilities.values()):
            continue
        loc = geocode(name)
        if loc:
            facilities[len(facilities)] = dict(name=name, loc=loc, type=t)
    # 保证每类至少 1 个; 不足则用东胜区质心附近合成补(标注 synthetic)
    while len([f for f in facilities.values() if f["type"] == "resource"]) < 2:
        facilities[len(facilities)] = dict(name="(synthetic resource)", loc="109.99,39.84", type="resource", synthetic=True)
    while len([f for f in facilities.values() if f["type"] == "landfill"]) < 1:
        facilities[len(facilities)] = dict(name="(synthetic landfill)", loc="109.96,39.92", type="landfill", synthetic=True)
    while len([f for f in facilities.values() if f["type"] == "transfer"]) < 1:
        facilities[len(facilities)] = dict(name="(synthetic transfer)", loc="110.00,39.86", type="transfer", synthetic=True)
    # 2) 产生区: 真实东胜街道/镇
    zones = ["东胜区富兴街道", "东胜区交通街道", "东胜区公园街道", "东胜区林荫街道",
             "东胜区罕台镇", "东胜区铜川镇", "东胜区泊尔江海子镇"]
    gen_zones = []
    for z in zones:
        loc = geocode(z)
        if loc: gen_zones.append(dict(name=z, loc=loc))
        time.sleep(0.2)
    # 3) 距离矩阵(驾车, 逐对调用最稳)
    allnodes = [f for f in facilities.values()] + gen_zones
    locs = [n["loc"] for n in allnodes]
    mat = [[None] * len(locs) for _ in range(len(locs))]
    for i, o in enumerate(locs):
        for j, d in enumerate(locs):
            res = distance(o, d)   # 单 origin
            if res and res[0] and res[0][0]:
                mat[i][j] = dict(dist_km=round(float(res[0][0]) / 1000.0, 2),
                                 dur_h=round(float(res[0][1]) / 3600.0, 3))
            time.sleep(0.12)
        print(f"  matrix row {i+1}/{len(locs)} done", flush=True)
    net = dict(facilities=list(facilities.values()), gen_zones=gen_zones, nodes=allnodes, matrix=mat,
               city="鄂尔多斯东胜区", source="Gaode Maps API (real driving)")
    json.dump(net, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return net

def build_real_instance(n_periods=6):
    """把真实网络转成 CDW-MDCA 实例。产生事件落在真实街道/镇; 汇用真实设施。"""
    import numpy as np, math
    rng = np.random.default_rng(42)
    net = build_real_network()
    nodes = net["nodes"]; M_ = net["matrix"]
    # 汇
    sinks = []; sid = 0
    tot_cap_scale = 200000.0  # 量级
    frac = {"backfill": 0.25, "resource": 0.30, "landfill": 0.60}
    for fi, f in enumerate(net["facilities"]):
        sinks.append(dict(id=sid, type=f["type"], name=f.get("name"),
                          cap=round(frac.get(f["type"], 0.3) * tot_cap_scale / (n_periods), 0),
                          fee=P.SINK_FEE[f["type"]], revenue=P.SINK_REVENUE[f["type"]],
                          dist=None, cycle_h=None, real=True))
        sid += 1
    transfers = []
    for f in net["facilities"]:
        if f["type"] == "transfer":
            transfers.append(dict(id=len(transfers), cap=P.TRANSFER_SORT_THROUGHPUT,
                                  hold=P.TRANSFER_HOLD_COST, fixed=P.TRANSFER_FIXED_PER_PERIOD,
                                  dist=None, cycle_h=None, sort_loss=P.SORT_LOSS, real=True))
    # 产生事件(落在真实产生区)
    events = []
    for i in range(8):
        z = net["gen_zones"][i % len(net["gen_zones"])]
        vol_m3 = float(np.clip(rng.lognormal(math.log(P.VOL_MEDIAN_M3), P.VOL_LOGN_SIGMA), P.VOL_MIN_M3, P.VOL_MAX_M3))
        cls = str(rng.choice(P.CLASSES, p=[P.COMPOSITION[c] for c in P.CLASSES]))
        events.append(dict(id=i, cls=cls, vol_m3=round(vol_m3, 1), vol_t=round(vol_m3 * P.M3_TO_T, 1),
                           release=int(rng.integers(0, n_periods)), zone=z["name"], node_idx=len(net["facilities"]) + (i % len(net["gen_zones"]))))
    # 注入真实距离/时间(健壮: 守 None 单元)
    nfac = len(net["facilities"])
    gz_idx = list(range(nfac, nfac + len(net["gen_zones"])))
    def cell(i, j):
        row = M_[i] if i < len(M_) else None
        return row[j] if (row and j < len(row) and row[j]) else None
    all_d = [cell(i, j)["dist_km"] for i in range(len(M_)) for j in range(len(M_))
             if cell(i, j) and cell(i, j).get("dist_km")]
    gmed = float(np.median(all_d)) if all_d else 15.0
    fac_of = {f["type"]: [k for k, fn in enumerate(net["facilities"]) if fn["type"] == f["type"]]
              for f in net["facilities"]}
    # 汇: 每个汇对应一个真实设施(sink.id == 该设施在 net["facilities"] 的索引, 因按序构建)
    for s in sinks:
        fi = s["id"]
        ds = [cell(gi, fi)["dist_km"] for gi in gz_idx if cell(gi, fi) and cell(gi, fi).get("dist_km")]
        du = [cell(gi, fi)["dur_h"] for gi in gz_idx if cell(gi, fi) and cell(gi, fi).get("dur_h")]
        s["dist"] = float(np.median(ds)) if ds else gmed
        s["cycle_h"] = round((float(np.median(du)) if du else 2 * s["dist"] * P.CYCLE_HOURS_PER_KM)
                             + P.LOAD_UNLOAD_H, 3)
    # 中转: 用 transfer 类设施到产生区的真实距离
    tr_fis = fac_of.get("transfer", [])
    for j in transfers:
        ds = [cell(gi, fi)["dist_km"] for fi in tr_fis for gi in gz_idx
              if cell(gi, fi) and cell(gi, fi).get("dist_km")]
        j["dist"] = float(np.median(ds)) if ds else gmed
        j["cycle_h"] = round(2 * j["dist"] * P.CYCLE_HOURS_PER_KM + P.LOAD_UNLOAD_H, 3)
    # 车队(自动)
    total_t = sum(e["vol_t"] for e in events)
    trips_per_night = max(1, int(P.NIGHT_HOURS / 1.5))
    needed = max(4, int(np.ceil(total_t / (P.TRUCK_CAP_T * trips_per_night * 7 * n_periods) / 0.85)))
    vehicles = []
    for vi in range(needed):
        vehicles.append(dict(id=vi, authorized=str(rng.choice(P.CLASSES, p=[P.COMPOSITION[c] for c in P.CLASSES])), cap=P.TRUCK_CAP_T))
    return dict(size="real_dongsheng", n_events=len(events), n_transfer=len(transfers), n_sinks=len(sinks),
                n_periods=n_periods, fleet_size=len(vehicles), seed=42, events=events, transfers=transfers,
                sinks=sinks, vehicles=vehicles, params=P.describe(), real_network=net["city"])

if __name__ == "__main__":
    inst = build_real_instance(6)
    ig.save(inst, os.path.join(ROOT, "data", "processed", "instance_real_dongsheng.json"))
    print(f"real instance: {inst['n_events']} events, {inst['n_transfer']} transfer, {inst['n_sinks']} sinks, fleet {inst['fleet_size']}")
    print("sinks (real):", [(s.get('name'), s['type'], round(s['dist'],1), 'km') for s in inst['sinks']])
    print("real network:", inst['real_network'])
