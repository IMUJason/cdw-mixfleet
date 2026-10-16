# -*- coding: utf-8 -*-
"""抓取东胜区及下级街道/镇行政边界(Amap 行政区 API), 存为规范化 JSON。
输出: data/external/dongsheng_boundaries.json
"""
import json, os, sys, urllib.request, urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY = open(os.path.join(ROOT, "data", "external", ".amap_key"), encoding="utf-8").read().strip()

def district_query(keywords, subdistrict=1, extensions="all"):
    q = urllib.parse.urlencode(dict(keywords=keywords, subdistrict=subdistrict,
                                    extensions=extensions, key=KEY))
    url = "https://restapi.amap.com/v3/config/district?" + q
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))

def parse_polyline(poly):
    """Amap polyline -> list of rings, each ring a list of [lon,lat]."""
    rings = []
    if not poly:
        return rings
    for part in poly.split("|"):
        pts = []
        for pair in part.split(";"):
            if not pair:
                continue
            lon_s, lat_s = pair.split(",")[:2]
            pts.append([float(lon_s), float(lat_s)])
        if len(pts) >= 3:
            rings.append(pts)
    return rings

def find_ds(resp):
    ds = None
    for d in resp.get("districts", []):
        if d.get("adcode") == "150602" or d.get("name") == "东胜区":
            ds = d
            break
    if ds is None:
        for d in resp.get("districts", []):
            for sub in d.get("districts", []):
                if sub.get("adcode") == "150602" or sub.get("name") == "东胜区":
                    ds = sub
                    break
    return ds

def main():
    raw = district_query("东胜区", subdistrict=1, extensions="all")
    os.makedirs(os.path.join(ROOT, "data", "external"), exist_ok=True)
    raw_path = os.path.join(ROOT, "data", "external", "amap_dongsheng_district_raw.json")
    json.dump(raw, open(raw_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    ds = find_ds(raw)
    if ds is None:
        print("NOT FOUND:", json.dumps(raw, ensure_ascii=False)[:500])
        sys.exit(1)

    out = {
        "source": "Amap district API (extensions=all, queried 2026)",
        "city": "Ordos / Dongsheng (鄂尔多斯东胜区)",
        "district": {
            "name": ds.get("name"), "adcode": ds.get("adcode"),
            "center": [float(x) for x in ds.get("center", "0,0").split(",")],
            "rings": parse_polyline(ds.get("polyline")),
        },
        "subdistricts": [],
    }

    # 子级边界需逐个按名称查询(带 extensions=all 才有 polyline)
    drings = out["district"]["rings"]
    dlons = [p[0] for r in drings for p in r]
    dlats = [p[1] for r in drings for p in r]
    lon0, lon1, lat0, lat1 = min(dlons), max(dlons), min(dlats), max(dlats)

    def in_district(center):
        lon, lat = center
        return (lon0 - 0.5 <= lon <= lon1 + 0.5) and (lat0 - 0.5 <= lat <= lat1 + 0.5)

    def resolve(name):
        for kw in (name, "东胜区" + name):
            resp = district_query(kw, subdistrict=0, extensions="all")
            for cand in resp.get("districts", []):
                if cand.get("name") == name and cand.get("polyline"):
                    c = [float(x) for x in cand.get("center", "0,0").split(",")]
                    if in_district(c):
                        return cand
        return None

    print("fetching sub-district boundaries one by one ...")
    for s in ds.get("districts", []):
        name = s.get("name")
        if not name:
            continue
        sd = resolve(name)
        rings = parse_polyline(sd.get("polyline")) if sd else []
        out["subdistricts"].append({
            "name": name, "adcode": s.get("adcode"),
            "center": [float(x) for x in s.get("center", "0,0").split(",")],
            "rings": rings,
        })
        print("  ", name, "rings", len(rings))
    out_path = os.path.join(ROOT, "data", "external", "dongsheng_boundaries.json")
    json.dump(out, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    lons = [p[0] for r in out["district"]["rings"] for p in r]
    lats = [p[1] for r in out["district"]["rings"] for p in r]
    print("district rings:", len(out["district"]["rings"]), "pts:", len(lons))
    print("bbox: lon %.4f-%.4f, lat %.4f-%.4f" % (min(lons), max(lons), min(lats), max(lats)))
    print("subdistricts with geometry:", sum(1 for s in out["subdistricts"] if s["rings"]))
    print("saved ->", out_path)

if __name__ == "__main__":
    main()
