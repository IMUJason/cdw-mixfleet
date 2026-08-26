"""CDW-MDCA 校准参数表。每个参数带溯源 ID（见 docs/PROVENANCE.md）。
所有数值来源于实际文献/法规/案例，可追溯。"""
import numpy as np

# ---- 溯源 ID 索引（简记），完整出处见 docs/PROVENANCE.md ----
# P01 东胜区台账 E1 实证(81 条, 2023-25)
# P02 多省 2024-25 联单/分类运输法规 E2(广东/北京/山东/辽宁...)
# P03 4Step_CDW facility_list.csv / city_list.csv / plan2_parameters(团队数据)
# P04 infrastructure_demolition_waste_1978_2018.xlsx (14 材料组分, 4Step)
# P05 Wu 2025 / 海口郭帅2024 / 中国砂石协会(运输/处置/再生料价格)
# P06 上海崇明/重庆 中转站案例 E2(60 t/d 模块, 风选磁选筛分)
# P07 中国循环经济协会 / 生态环境部 2025(回填占比、综合利用率)
# P08 各城市夜间限行规定 E2(武汉/长沙/深圳/南京...);南京白天有限开禁

# ================= 物料与换算 =================
CLASSES = ["earth", "demolition", "renovation"]          # 工程渣土 / 拆除垃圾 / 装修垃圾 (P02 北京分类)
# 组分比例(占总量) — 由 P04 14 材料聚合 + P02 分类标定
COMPOSITION = {"earth": 0.60, "demolition": 0.25, "renovation": 0.15}
M3_TO_T = 1.6                                            # m³ → 吨, CDW 混合密度 (P05 文献)

# ================= 产废事件 =================
VOL_MEDIAN_M3 = 10_000.0                                 # 单事件方量中位 (P01 东胜:中位 1 万 m³)
VOL_LOGN_SIGMA = 1.1                                     # 右偏(东胜:120~105000 m³, std≈mean)
VOL_MIN_M3, VOL_MAX_M3 = 200.0, 120_000.0                # 东胜区间 (P01)

# ================= 车辆与多程 =================
TRUCK_CAP_T = 15.0                                       # 自卸车单车载重 ~12-15 m³ ≈ 15 t (P05)
NIGHT_HOURS = 8.0                                        # 夜间窗 22:00-06:00 (P08)
CYCLE_HOURS_PER_KM = 1.0 / 35.0                          # 往返平均车速 ~35 km/h → 单程时间
LOAD_UNLOAD_H = 0.5                                      # 装卸 0.5 h/趟
FTL_SVC_H = 0.0                                          # FTL 每趟对称服务时间(默认 0=仅驾驶; 敏感性实验设 0.5)
LTL_STOP_H = 0.0                                         # LTL 每访问站点固定装卸时间(默认 0=仅按吨位计; 敏感性实验设 0.1/0.2)
UNIT_TRANSPORT = 0.80                                    # 元/(t·km) — 取 P03(0.38-0.42) 与 P05(1.0-1.5) 的折中保守值

# ================= 汇(处置点) =================
# 类别兼容矩阵: 哪类废物可去哪种汇 —— 仅 CDW-MDCA 历史主线使用 (model.py/benders.py)。
# MixFleet 主线的"每类唯一合规汇"由下方 MIXFLEET_SINK 定义 (见 mixfleet_model.sink_for_class)。
SINK_COMPAT = {
    "earth":      {"backfill", "resource", "landfill", "transfer"},
    "demolition": {"resource", "landfill", "transfer"},
    "renovation": {"transfer"},                          # MDCA 主线口径 (装修先经中转分拣)
}
# MixFleet 主线: 每类唯一合规汇 (P02 分类处置; 联单固定汇点).
# resource = 分选-资源化综合处置中心(先分拣再资源化/填埋分流), 装修与拆除垃圾联单均固定送此,
# "未分拣严禁外运"指不得未经分拣直接倾倒, 不强制经独立中转站。
MIXFLEET_SINK = {"earth": "backfill", "demolition": "resource", "renovation": "resource"}
# 处置费/再利用收益的生效值在文末"运营层成本(P10)"块统一定义(回填 20/8 等)。
# 注: 2026-08-13~14 的 CDW-MDCA 历史结果使用过早期块(backfill 5/25), 已并入 P10 单一定义, 避免静默覆盖。
SINK_FEES_LEGACY_MDCA = {"backfill": 5.0, "resource": 45.0, "landfill": 30.0, "transfer": 12.0}      # 仅历史参考
SINK_REVENUES_LEGACY_MDCA = {"backfill": 25.0, "resource": 60.0, "landfill": 0.0, "transfer": 0.0}   # 仅历史参考
# 处置/回填点距产生区 (P01 碾红线/20km + P05 10-25km)
DIST = {"backfill": (5, 15), "resource": (12, 25), "landfill": (15, 30), "transfer": (3, 10)}
SINK_CAP_PER_PERIOD = {"backfill": 600.0, "resource": 400.0, "landfill": 500.0, "transfer": 60.0 * 7}  # t/期(周)

# ================= 中转站 =================
TRANSFER_SORT_THROUGHPUT = 60.0 * 7                      # t/期(60 t/d × 7d, P06 模块化)
TRANSFER_HOLD_COST = 2.0                                 # 元/(t·期) 暂存持有 (P05 量级)
TRANSFER_FIXED_PER_PERIOD = 8_000.0                      # 元/期 摊销(3000-5000万建/25年/52周, P05 郭帅2024)
SORT_LOSS = 0.10                                         # 分选损耗 10%

# ================= 政策 =================
RESOURCE_QUOTA = 0.55                                    # 强制资源化率(回填+资源化)/总量 ≥ 55% (P02 政策目标)
LANDFILL_CAP_FRAC = 0.30                                 # 填埋占比上限 30%

# ================= 不确定性(事件驱动) =================
VOL_CV = 0.30                                            # 产废量变异系数(场景扰动)
RELEASE_SPREAD = True                                    # 释放期随机分布(事件驱动, P01/Shao2026)

# ================= 成本汇总权重(目标函数) =================
SHORTAGE_PENALTY = 150.0                                 # 元/t 未及时清运惩罚 (合同违约金折算)

# ================= 运营层成本(承运商视角, 按车次计费) — P10 =================
# 依据: 许妙2019/Yu2025/Wang2022 范式 C=Σ n_ikt·(起步价+里程价×往返距离); 欠载不省钱
TRIP_FIXED = 400.0                                       # 元/趟 固定出车费(司机+油起步+折旧) Yu2025(750元/车·天)折算
TRIP_PER_KM = 3.9                                        # 元/车·km 里程价(柴油, Yu2025成都)
FLEET_FIXED_PER_DAY = 750.0                              # 元/车·天 车队固定(Yu2025)
# 处置费/再利用收益(按吨, P05+协会): 回填/资源化/填埋
SINK_FEE = {"backfill": 20.0, "resource": 45.0, "landfill": 30.0, "transfer": 12.0}
SINK_REVENUE = {"backfill": 8.0, "resource": 60.0, "landfill": 0.0, "transfer": 0.0}

def describe():
    return dict(classes=CLASSES, composition=COMPOSITION,
                vol_median_m3=VOL_MEDIAN_M3, truck_cap_t=TRUCK_CAP_T,
                unit_transport=UNIT_TRANSPORT, resource_quota=RESOURCE_QUOTA)

# ================= 求解器选择(优先 CPLEX 教育版, 退化 CBC) =================
import pulp as _pulp
def get_solver(msg=0, timeLimit=120, gapRel=0.05, logPath=None, threads=None):
    """优先 CPLEX_PY(教育版无限制), 否则 CBC。kwargs 与 PULP_CBC_CMD 一致, 可直接替换。
    threads=None 用求解器默认(全部核); 并行筛选用小值限核(仅 CPLEX 生效, CBC 忽略)。"""
    try:
        import cplex  # noqa: F401
        kw = dict(msg=msg, timeLimit=timeLimit, gapRel=gapRel)
        if threads is not None: kw["threads"] = threads
        if logPath is not None: kw["logPath"] = logPath
        return _pulp.CPLEX_PY(**kw)
    except Exception:
        kw = dict(msg=1 if msg else 0, timeLimit=timeLimit, gapRel=gapRel)
        if logPath is not None: kw["logPath"] = logPath
        return _pulp.PULP_CBC_CMD(**kw)
