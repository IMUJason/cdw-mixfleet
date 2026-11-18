"""CDW-MixFleet 校准参数表。每个参数带溯源 ID（见 docs/PROVENANCE.md）。
所有数值来源于实际文献/法规/案例，可追溯。
仅含 MixFleet 调度模型实际使用的参数; 求解时常数随实例 CSV 的 [params] 快照存档。"""
import pulp as _pulp

# ---- 溯源 ID 索引（简记），完整出处见 docs/PROVENANCE.md ----
# P02 多省 2024-25 联单/分类运输法规(广东/北京/山东/辽宁...)
# P05 Wu 2025 / 海口郭帅2024 / 中国砂石协会(运输/处置/再生料价格)
# P08 各城市夜间限行规定(武汉/长沙/深圳/南京...);南京白天有限开禁
# P10 运营层成本(承运商按车次计费范式, Yu2025)

# ================= 物料与类别 =================
CLASSES = ["earth", "demolition", "renovation"]          # 工程渣土 / 拆除垃圾 / 装修垃圾 (P02 北京分类)

# ================= 车辆与多程 =================
TRUCK_CAP_T = 15.0                                       # 自卸车单车载重 ~12-15 m³ ≈ 15 t (P05)
NIGHT_HOURS = 8.0                                        # 夜间窗 22:00-06:00 (P08)
LOAD_UNLOAD_H = 0.5                                      # 装卸 0.5 h/趟(按吨位折算满载当量)
FTL_SVC_H = 0.0                                          # FTL 每趟对称服务时间(默认 0=仅驾驶; 敏感性实验设 0.5)
LTL_STOP_H = 0.0                                         # LTL 每访问站点固定装卸时间(默认 0=仅按吨位计; 敏感性实验设 0.1/0.2)

# ================= 汇(处置点) =================
# MixFleet 主线: 每类唯一合规汇 (P02 分类处置; 联单固定汇点)。
# resource = 分选-资源化综合处置中心(先分拣再资源化/填埋分流), 装修与拆除垃圾联单均固定送此,
# "未分拣严禁外运"指不得未经分拣直接倾倒, 不强制经独立中转站。
# 生效判定在 mixfleet_model.sink_for_class, 与本表一致。
MIXFLEET_SINK = {"earth": "backfill", "demolition": "resource", "renovation": "resource"}

# ================= 成本汇总权重(目标函数) =================
SHORTAGE_PENALTY = 150.0                                 # 元/t 未及时清运惩罚 (合同违约金折算)

# ================= 运营层成本(承运商视角, 按车次计费) — P10 =================
# 依据: Yu2025/Wang2022 范式 C=Σ n_ikt·(起步价+里程价×往返距离); 欠载不省钱
TRIP_FIXED = 400.0                                       # 元/趟 固定出车费(司机+油起步+折旧) Yu2025(750元/车·天)折算
TRIP_PER_KM = 3.9                                        # 元/车·km 里程价(柴油, Yu2025成都)
# 处置费/再利用收益(按吨, P05+协会): 回填/资源化/填埋
SINK_FEE = {"backfill": 20.0, "resource": 45.0, "landfill": 30.0}
SINK_REVENUE = {"backfill": 8.0, "resource": 60.0, "landfill": 0.0}

# ================= 求解器选择(优先 CPLEX 教育版, 退化 CBC) =================
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
