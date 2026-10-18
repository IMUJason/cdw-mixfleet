"""专业级论文图表 v5: 东胜案例图(矢量重绘边界+OSM骨干路网)+收敛曲线+基准双面板。
图1(调度网络示意)为 AI 绘制的静态资产(manuscript/fig1_network.png), 不由本脚本生成。
输出按论文图号命名: fig3/fig4/fig5。"""
import os, sys, json, math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle, Circle, FancyBboxPatch, Polygon
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIG = os.path.join(ROOT, "results", "figures")
NET = os.path.join(ROOT, "data", "external", "dongsheng_real_network.json")
BND = os.path.join(ROOT, "data", "external", "dongsheng_boundaries.json")
OSM = os.path.join(ROOT, "data", "external", "dongsheng_osm.json")

C = dict(ftl="#C0392B", ltl="#D68910", depot="#2C3E50", backfill="#27AE60",
         resource="#8E44AD", landfill="#7F8C8D", transfer="#2471A3",
         zone="#1B4F72", accent="#148F77")
plt.rcParams.update({"font.size": 13, "figure.dpi": 200, "font.family": "DejaVu Sans",
                     "axes.edgecolor": "#333", "axes.linewidth": 0.9})


def fig_bench():
    """fig5: 墙钟时间 + gap 双面板(读 mixfleet_bench.csv; certified 仅在有效处绘制)。"""
    import csv as _csv
    rows = list(_csv.DictReader(open(os.path.join(ROOT, "results", "tables", "mixfleet_bench.csv"),
                                     encoding="utf-8-sig")))
    xs = [r["instance"].split(":")[0] for r in rows]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.0, 3.9))
    cpx_t = [float(r["cpx_time"]) for r in rows]; heu_t = [float(r["heu_time"]) for r in rows]
    a1.plot(xs, cpx_t, "o-", color="#c44e52", label="CPLEX (0.1% tol, size-dependent limit)")
    a1.plot(xs, heu_t, "s-", color="#4c72b0", label="SA (fixed budget)")
    a1.set_ylabel("Wall-clock time (s)"); a1.set_xlabel("Instance")
    a1.set_ylim(0, max(cpx_t) * 1.28)          # 顶部留白防曲线顶边
    a1.legend(fontsize=9, loc="upper left", framealpha=0.92)
    a1.grid(alpha=0.3); a1.margins(x=0.08)
    gaps = [float(r["gap_pct"]) for r in rows]
    certs = [float(r["gap_certified_pct"]) for r in rows]
    a2.plot(xs, gaps, "o--", color="#55a868", label="vs. CPLEX incumbent")
    a2.plot(xs, certs, "s-", color="#4c72b0",
            label="certified vs. dual bound (XL loose)")
    a2.axhline(0, color="gray", ls=":", lw=1)
    a2.set_ylabel("Gap (%)"); a2.set_xlabel("Instance")
    a2.set_ylim(min(0, min(gaps) - 0.25), max(certs) * 1.18)
    a2.legend(fontsize=9, loc="upper left", framealpha=0.92)
    a2.grid(alpha=0.3); a2.margins(x=0.08)
    fig.tight_layout(); fig.savefig(os.path.join(FIG, "fig5_bench.pdf"), bbox_inches="tight"); plt.close(fig)
    print("fig5 OK")


def lonlat_to_pixel(lon, lat, center_lon, center_lat, zoom, img_w, img_h, scale=2):
    n = 2 ** zoom
    def merc(x, y):
        px = (x + 180.0) / 360.0 * n * 256
        lat_r = math.radians(y)
        py = (1 - math.log(math.tan(lat_r) + 1 / math.cos(lat_r)) / math.pi) / 2 * n * 256
        return px, py
    cx, cy = merc(center_lon, center_lat)
    px, py = merc(lon, lat)
    return img_w / 2 + (px - cx) * scale, img_h / 2 + (py - cy) * scale


# ---- 图4: 矢量重绘案例地图 ----
# 道路按等级渲染(骨干路网加深); 边界来自 Amap 行政区 API; 道路来自 OSM。
ROAD_STYLE = {
    "motorway":     (1.35, "#9a9a9a"),
    "trunk":        (1.05, "#aaaaaa"),
    "primary":      (0.78, "#b8b8b8"),
    "secondary":    (0.56, "#c8c8c8"),
    "tertiary":     (0.36, "#d7d7d7"),
    "residential":  (0.22, "#e7e7e7"),
    "unclassified": (0.22, "#e7e7e7"),
}

ZONE_LBL = {
    "东胜区富兴街道": "Fuxing Subdist.",
    "东胜区交通街道": "Jiaotong Subdist.",
    "东胜区公园街道": "Gongyuan Subdist.",
    "东胜区林荫街道": "Linyin Subdist.",
    "东胜区罕台镇": "Hantai Town",
    "东胜区泊尔江海子镇": "Boerjianghaizi Town",
}

FAC_LBL = {
    "resource": "CDW processing center",
    "transfer": "Standardized transfer station",
    "backfill": "Backfill point (rep.)",
    "landfill": "Landfill (rep.)",
}

FAC_MARK = {
    "resource": ("s", C["resource"]),
    "transfer": ("^", C["transfer"]),
    "backfill": ("D", C["backfill"]),
    "landfill": ("v", C["landfill"]),
}


def _fac_kind(f):
    """真实处理中心(resource)/转运站(transfer) 与合成回填点/填埋场 的符号区分。"""
    if f["type"] == "landfill":
        return "landfill"
    if "(synthetic" in f.get("name", ""):
        return "backfill"
    return f["type"]


def _draw_roads(ax, osm, lw_scale):
    segs = {k: [] for k in ROAD_STYLE}
    for r in osm["roads"]:
        if r["highway"] in segs:
            segs[r["highway"]].append(r["coords"])
    for hw, (lw, color) in ROAD_STYLE.items():
        if not segs[hw]:
            continue
        ax.add_collection(LineCollection(segs[hw], linewidths=lw * lw_scale,
                                         colors=color, alpha=1.0, zorder=2,
                                         capstyle="round", joinstyle="round"))


def _draw_anchors(ax, net, size, zone_r, label_fac=False, label_zone=False,
                  label_off=None):
    for f in net["facilities"]:
        lon, lat = [float(x) for x in f["loc"].split(",")]
        kind = _fac_kind(f)
        mk, cc = FAC_MARK[kind]
        ax.scatter(lon, lat, s=size, marker=mk, c=cc, ec="white", lw=0.9,
                   zorder=5)
        if label_fac:
            ax.text(lon, lat, FAC_LBL[kind], fontsize=7, color="#1a1a1a",
                    zorder=6, bbox=dict(fc="white", ec="none", alpha=0.78, pad=0.12))
    for g in net["gen_zones"]:
        lon, lat = [float(x) for x in g["loc"].split(",")]
        ax.add_patch(Circle((lon, lat), zone_r, fc=C["zone"], alpha=0.15,
                            ec=C["zone"], lw=1.0, zorder=3))
        ax.scatter(lon, lat, s=16, c=C["zone"], zorder=4)
        if label_zone:
            lbl = ZONE_LBL.get(g["name"], g["name"])
            dx, dy, ha = label_off.get(g["name"], (0, 0.008, "center")) \
                if label_off else (0, 0.008, "center")
            ax.text(lon + dx, lat + dy, lbl, fontsize=7, color="#1a1a1a",
                    ha=ha, va="center", zorder=6,
                    bbox=dict(fc="white", ec="none", alpha=0.78, pad=0.12))


def _scale_bar(ax, lon0, lat0, km, label):
    deg = km / (111.32 * math.cos(math.radians(lat0)))
    ax.plot([lon0, lon0 + deg], [lat0, lat0], color="#111", lw=2.6,
            solid_capstyle="butt", zorder=7)
    ax.text(lon0 + deg / 2, lat0 + 0.006, label, ha="center", va="bottom",
            fontsize=7.5, color="#111", zorder=7)


def _north_arrow(ax, x=0.965, ytop=0.90):
    ax.annotate("N", xy=(x, ytop), xycoords="axes fraction", fontsize=10,
                weight="bold", ha="center", va="bottom", zorder=8)
    ax.annotate("", xy=(x, ytop - 0.015), xytext=(x, ytop - 0.085),
                xycoords="axes fraction",
                arrowprops=dict(arrowstyle="-|>", lw=1.3, color="#333"), zorder=8)


def _draw_map_layers(ax, bnd, osm, net, view, road_lw=1.0,
                     fac_s=(185, 115), zone_s=(150, 90)):
    """在给定坐标窗口 view=(x0,x1,y0,y1) 内绘制边界/路网/设施/需求区图标。"""
    x0, x1, y0, y1 = view
    for ring in bnd["district"]["rings"]:
        ax.add_patch(Polygon([(p[0], p[1]) for p in ring], closed=True,
                             fc="#fcfcfa", ec="#c5c5c5", lw=0.8, zorder=1))
    _draw_roads(ax, osm, road_lw)
    for f in net["facilities"]:
        lon, lat = [float(x) for x in f["loc"].split(",")]
        if not (x0 <= lon <= x1 and y0 <= lat <= y1):
            continue
        mk, cc = FAC_MARK[_fac_kind(f)]
        ax.scatter(lon, lat, s=fac_s[0], marker=mk, c="white", ec="white", lw=0,
                   zorder=5)
        ax.scatter(lon, lat, s=fac_s[1], marker=mk, c=cc, ec="#333333", lw=0.8,
                   zorder=6)
    for g in net["gen_zones"]:
        lon, lat = [float(x) for x in g["loc"].split(",")]
        if not (x0 <= lon <= x1 and y0 <= lat <= y1):
            continue
        ax.scatter(lon, lat, s=zone_s[0], marker="o", c="white", ec="white", lw=0,
                   zorder=4)
        ax.scatter(lon, lat, s=zone_s[1], marker="o", c=C["zone"], ec="#333333",
                   lw=0.8, zorder=5)


def fig_map():
    bnd = json.load(open(BND, encoding="utf-8"))
    osm = json.load(open(OSM, encoding="utf-8"))
    net = json.load(open(NET, encoding="utf-8"))

    fig, ax = plt.subplots(figsize=(8.4, 5.0))
    # 主图: 横向拉宽以真实容纳最西侧的泊尔江海子镇与罕台镇。
    view = (109.345, 110.135, 39.775, 39.955)
    x0, x1, y0, y1 = view
    ax.set_xlim(x0, x1); ax.set_ylim(y0, y1)
    ax.set_aspect(1.0 / math.cos(math.radians(39.85)))
    ax.axis("off")
    _draw_map_layers(ax, bnd, osm, net, view, fac_s=(235, 150), zone_s=(185, 115))

    # 直接标注若干关键 POI(引线指向对应图标), 其余类别交给图例。
    label_box = dict(fc="white", ec="none", alpha=0.85, pad=0.2)
    arr = dict(arrowstyle="-", color="#666", lw=0.7, shrinkA=1, shrinkB=2)
    ax.text(109.386, 39.874, "Boerjianghaizi Town", fontsize=8.5, color="#303030",
            ha="center", va="bottom", zorder=7, bbox=label_box)
    ax.text(109.843, 39.853, "Hantai Town", fontsize=8.5, color="#303030",
            ha="right", va="bottom", zorder=7, bbox=label_box)
    ax.annotate("Transfer station", xy=(110.027, 39.826),
                xytext=(110.056, 39.870), fontsize=8.3, color="#303030",
                ha="left", va="bottom", zorder=8, bbox=label_box, arrowprops=arr)
    ax.text(109.985, 39.800, "Dongsheng urban core", fontsize=8.3, color="#303030",
            ha="center", va="top", zorder=7, bbox=label_box)

    handles = [
        Line2D([], [], marker="s", color=C["resource"], ls="", ms=8, mec="#333",
               label="CDW processing center"),
        Line2D([], [], marker="^", color=C["transfer"], ls="", ms=8.5, mec="#333",
               label="Standardized transfer station"),
        Line2D([], [], marker="D", color=C["backfill"], ls="", ms=7.5, mec="#333",
               label="Backfill point (representative)"),
        Line2D([], [], marker="v", color=C["landfill"], ls="", ms=8.5, mec="#333",
               label="Landfill (representative)"),
        Line2D([], [], marker="o", color=C["zone"], ls="", ms=8, mec="#333",
               label="Demand sub-district"),
    ]
    # 图例置于地图右侧外置竖排, 不遮挡任何地理元素; 版权行移到地图下方独立一行
    ax.legend(handles=handles, loc="upper left", fontsize=7.6, frameon=False,
              facecolor="white", framealpha=0.95, edgecolor="#d0d0d0",
              handletextpad=0.5, labelspacing=0.5, ncol=1,
              bbox_to_anchor=(1.03, 1.0))
    ax.text(0.0, -0.045,
            "Boundary \u00a9 Amap (autoNavi) API, 2026  |  "
            "Roads \u00a9 OpenStreetMap contributors (ODbL)",
            transform=ax.transAxes, fontsize=6.6, color="#666",
            va="top", ha="left")
    _scale_bar(ax, 109.52, 39.945, 10, "10 km")
    _north_arrow(ax, x=0.045, ytop=0.93)

    fig.savefig(os.path.join(FIG, "fig4_map.pdf"), bbox_inches="tight",
                pad_inches=0.05, dpi=200)
    plt.close(fig); print("fig4 OK")


def fig_convergence():
    """真实 SA 收敛曲线: 读取 results/logs/sa_trace_{S,M,L,X}.csv(bench 重跑时的逐次改进轨迹)。"""
    import csv as _csv
    import glob
    traces = sorted(glob.glob(os.path.join(ROOT, "results", "logs", "sa_trace_*.csv")))
    if not traces:
        print("sa_trace_*.csv missing - run run_mixfleet_bench.py first; skip fig3")
        return
    fig, ax = plt.subplots(figsize=(7.0, 3.8))
    # Okabe-Ito 色盲安全色板 + 线型/标记区分(按文件名显式映射, 防字母序错配)
    styles = {"S": ("#D55E00", "-"), "M": ("#0072B2", "--"), "L": ("#009E73", "-."),
              "X": ("#CC79A7", ":"), "XL": ("#56B4E9", "-")}
    for path in traces:
        name = os.path.basename(path)[len("sa_trace_"):-len(".csv")]
        if name not in styles:
            continue
        cc, ls = styles[name]
        pts = [(float(r["t_s"]), float(r["best_cost"])) for r in
               _csv.DictReader(open(path, encoding="utf-8-sig"))]
        if not pts: continue
        xs, ys = zip(*pts)
        ax.plot(xs, [y / 1e3 for y in ys], lw=1.6, ls=ls, color=cc, label=name,
                drawstyle="steps-post", markevery=max(1, len(xs) // 8),
                marker="o", ms=3.5)
    ax.set_xlabel("Wall-clock time (s)"); ax.set_ylabel("Best objective ($10^3$ CNY)")
    # 图例放右下: 平台期曲线集中在左侧与中部, 右下为空白区(避免遮挡 M/S 轨迹)
    ax.legend(title="Instance", fontsize=9, framealpha=0.92, loc="lower right")
    ax.grid(alpha=0.25, lw=0.6)
    ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
    fig.savefig(os.path.join(FIG, "fig3_convergence.pdf"), bbox_inches="tight", pad_inches=0.05)
    plt.close(fig); print("fig3 OK (real traces)")


if __name__ == "__main__":
    fig_map(); fig_convergence(); fig_bench()
    print("ALL ->", FIG)
