# -*- coding: utf-8 -*-
"""从 OpenStreetMap (Overpass API) 抓取东胜区骨干路网与行政区边界。
输出: data/external/dongsheng_osm.json
"""
import json, os, sys, urllib.request, urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BOUNDS = json.load(open(os.path.join(ROOT, "data", "external", "dongsheng_boundaries.json"),
                         encoding="utf-8"))
lons = [p[0] for r in BOUNDS["district"]["rings"] for p in r]
lats = [p[1] for r in BOUNDS["district"]["rings"] for p in r]
S, W, N, E = min(lats) - 0.15, min(lons) - 0.2, max(lats) + 0.15, max(lons) + 0.2
BBOX = "%.4f,%.4f,%.4f,%.4f" % (S, W, N, E)
print("bbox:", BBOX)

QUERY = f"""
[out:json][timeout:120];
(
  way["highway"~"^(motorway|trunk|primary|secondary|tertiary|residential|unclassified)$"]({BBOX});
  relation["boundary"="administrative"]["admin_level"~"^(8|9|10)$"]({BBOX});
);
out geom;
"""

ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

def fetch():
    last_err = None
    for ep in ENDPOINTS:
        try:
            data = urllib.parse.urlencode({"data": QUERY}).encode("utf-8")
            req = urllib.request.Request(ep, data=data,
                                         headers={"User-Agent": "cdw-mixfleet/1.0 (research map figure)"})
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            last_err = e
            print("endpoint failed:", ep, e)
    raise RuntimeError("all overpass endpoints failed: %s" % last_err)

def main():
    resp = fetch()
    roads, boundaries = [], []
    for el in resp.get("elements", []):
        if el.get("type") != "way":
            continue
        tags = el.get("tags", {})
        coords = [[p["lon"], p["lat"]] for p in el.get("geometry", [])]
        if len(coords) < 2:
            continue
        if "highway" in tags:
            roads.append({"name": tags.get("name", ""),
                          "highway": tags["highway"], "coords": coords})
        elif tags.get("boundary") == "administrative":
            boundaries.append({"name": tags.get("name", ""),
                               "level": int(tags.get("admin_level", 99)), "coords": coords})
    out = {"source": "OpenStreetMap contributors (ODbL), Overpass API, queried 2026",
           "bbox": [S, W, N, E], "roads": roads, "boundaries": boundaries}
    path = os.path.join(ROOT, "data", "external", "dongsheng_osm.json")
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    from collections import Counter
    cnt = Counter(r["highway"] for r in roads)
    print("roads:", len(roads), dict(cnt))
    for b in boundaries[:40]:
        print("  bnd L%d" % b["level"], b["name"], len(b["coords"]), "pts")
    print("boundaries:", len(boundaries), "-> saved", path)

if __name__ == "__main__":
    main()
