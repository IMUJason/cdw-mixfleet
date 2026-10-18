# 数据与参数溯源（Provenance）

> 每个模型参数都可追溯到具体文献/法规/案例/团队数据。论文中所有数字可经 `src/` 脚本复现。

## 溯源 ID 对照表

| ID | 来源 | 类型 | 在本项目位置 |
|----|------|------|--------------|
| P01 | 鄂尔多斯东胜区建筑垃圾台账 2023-25(81 条) | E1 实证(启发，**因合规不入论文**) | 仅用于算术标定(方量中位/区间)，原始数据不在库 |
| P02 | 多省 2024-25 法规:广东/北京/山东/辽宁/乌鲁木齐/滕州/越秀/阿巴嘎旗 联单+分类运输+夜间限行 | E2 法规 | — (WebSearch 核实链接见 v2 文档) |
| P03 | 团队 4Step_CDW 数据:facility_list.csv / city_list.csv / plan2_parameters_for_optimization.csv | 团队既有 | `data/parameters/`(已拷入) |
| P04 | infrastructure_demolition_waste_1978_2018.xlsx (14 材料组分) | 团队既有(4Step) | `data/parameters/`(已拷入) |
| P05 | 已发表案例:Wu 2025(上海航运)/Kang&Tan 2025(香港)/郭帅 2024(海口)/Alibakhshi 2024(德黑兰)/中国砂石协会 | E2 文献 | 见 `选题_v2_证据核查版.md` |
| P06 | 中转站案例:上海崇明分拣中转站/重庆全链条/模块化 60 t/d | E2 | WebSearch 链接 |
| P07 | 中国循环经济协会/生态环境部 2025(回填占比、综合利用率) | E2 | 核查 agent 报告 |
| P08 | 夜间限行规定:武汉/长沙/深圳/济南/南京白天有限开禁 | E2 | 核查 agent 报告 |

## 参数 → 溯源映射(`src/params.py`)

| 参数 | 值 | 溯源 |
|------|----|------|
| CLASSES & COMPOSITION (earth .60/dem .25/ren .15) | 类别比例 | P02 北京分类 + P04 14 材料聚合 |
| VOL_MEDIAN_M3 = 10000 | 单事件方量中位 | P01 东胜(中位 1 万 m³) |
| VOL 区间 200–120000 | 方量范围 | P01 东胜(min 120, max 105000) |
| M3_TO_T = 1.6 | m³→吨 | P05 CDW 混合密度文献 |
| TRUCK_CAP_T = 15 | 单车载重 | P05 自卸车 12-15 m³ |
| NIGHT_HOURS = 8 | 夜间窗 | P08(22:00-06:00) |
| UNIT_TRANSPORT = 0.80 元/(t·km) | 运输单价 | P03(0.38-0.42)与 P05(1.0-1.5)折中保守 |
| SINK_FEE / SINK_REVENUE | 处置费/再利用收益 | 生效值见 P10 段(回填 20/8, 资源化 45/60, 填埋 30/0); 早期 MDCA 历史结果曾用 backfill 5/25(见 params.py LEGACY 注) |
| DIST (backfill 5-15 / resource 12-25 / landfill 15-30 / transfer 3-10 km) | 廊道距离 | P01(碾红线/20km) + P05(10-25km) |
| SINK_CAP auto-scale | 汇容量 | 按总量自动标定(target_util 0.9)，量级校验 P03 facility_list |
| TRANSFER 60 t/d module | 中转模块 | P06 |
| TRANSFER_FIXED (3000-5000 万摊销) | 中转建设费 | P05 郭帅 2024 |
| SORT_LOSS = 0.10 | 分选损耗 | P06 工艺经验值 |
| RESOURCE_QUOTA = 0.55 | 资源化率配额 | P02 政策目标(60%，取 55 保守) |
| LANDFILL_CAP = 0.30 | 填埋上限 | P02 |
| VOL_CV = 0.30 | 产废量变异系数 | P01 跨年波动 + 经验 |
| SHORTAGE_PENALTY = 150 元/t(基线; 敏感性 50/150/500) | 未及时清运惩罚 | 合同违约金折算(承运侧合同惯例); Wu2025 量级交叉核对 |
| Fleet auto-size | 车队规模 | 按总量×0.95 利用率自动配车，按组分比例分配专营 |

## 算例生成与求解(可复现, MixFleet 主线)
- 实例生成与配置:`src/inst_config.py` 统一入口(标定车队 + 单夜预算 fleet_budget=NIGHT_HOURS=8h, trips_per_vehicle=R=8); 全部实验脚本共用。
- 车队标定:`results/tables/calibration_proposal.csv` — 按需求×0.75-0.80 利用率配车, 类别专营比例与需求组分一致(S 1e+4d+2r / M 1e+8d+5r / L 1e+8d+6r / X 2e+15d+8r)。
- 求解器:PuLP + CPLEX 22.1.1(教育版; 0.1% 容差 + best-bound 认证), CBC 兜底; `run_mixfleet_bench.py` / `run_mixfleet_seeds.py` / `run_sensitivity.py` / `run_mode_counterfactual.py` / `run_sa_restarts.py` → `results/tables/*.csv`。
- 模型: `mixfleet_model.build_mip` 含吨位流强化(single-commodity flow, LP gap 54-74% → 11%)。
- 报告口径:SA 侧所有报告成本 = `src/reprice.py` 精确重定价(结构固定、载荷自由 LP, 与 CPLEX 同口径); SA 内部 first-fit evaluate 仅用于搜索。
- 所有结果数字来自脚本真实运行，论文数字均可在对应 CSV 找到(审计: `src/audit_numbers.py`)。

## 现实特征 → 模型构件 对照(见 MODEL_SPEC.md)
F1 释放期→event_bal; F2 多程→ntrip 整数+link; F3 固定廊道→dist/cycle_h 给定; F4 类别专营→fleet_by_cls 时间约束; F5 中转→inv_bal+sort 吞吐; F6 异质汇→sink_compat+cap; 政策→reuse/landfill 约束。

## P09 真实路网(东胜区, 高德 API) — 用于真实案例(Result 6)
- 设施坐标: 高德 POI 搜索("建筑垃圾处理/消纳/中转/资源化", city=东胜区 adcode 150602) → 真实设施(综合处理中心 110.077485,39.894994; 1号标准转运站 110.027225,39.825925)。
- 产生区: 真实街道/镇(富兴/交通/公园/林荫/罕台/铜川/泊尔江海子)地理编码。
- OD 驾车距离/时长: 高德 /v3/distance API(type=1 驾车), 逐对调用, 缓存 data/external/dongsheng_real_network.json。
- API key 存 data/external/.amap_key(**已 gitignore, 不入仓库**)。
- 注: POI 覆盖不全处用代表性坐标补充(标注 synthetic); 事件方量为标定估计(非真实台账, 因合规)。

## P10 运营层成本模型(承运商视角, 按车次计费) — MixFleet 专用
- **范式**: C = Σ 车次×(起步价+里程价×距离), 许妙&袁红平2019(工业工程,DOI:10.3969/j.issn.1007-7375.2019.05.011, 整数车次×额定载重≥运量); Wang/Yi/Liu 2022 (Mathematics 10(22):4340, 香港 c=64.14+0.33D USD/趟); Yu et al. 2025 (arXiv:2504.10955/Transportmetrica A, 成都: 固定750元/车·天+变动).
- **TRIP_FIXED=400元/趟**: Yu2025(750元/车·天折算)+Wang2022(60USD≈430元)。
- **TRIP_PER_KM=3.9元/车·km**: Yu2025 成都柴油(7.8元/L×50L/100km)。
- **FLEET_FIXED_PER_DAY=750元/车·天**: Yu2025。
- **处置费(元/t)**: 回填20(嵊州10/上海公众填料35区间内), 资源化45(北京指导价), 填埋30(北京指导价; 上海100高值可做敏感性)。
- **再利用收益(元/t)**: 资源化60(砂石协会66.5-97取保守), 回填8(嵊州购土2-砂石替代区间保守)。
- **车载重 W=15t**: Zhang&Ahmed 2022 (Automation in Construction, 8×4合规14-18t)。
- **按车次计费 vs 按吨公里**: 战略层文献(Kang&Tan/Xu Xin/郭帅)按吨×距离; 运营层(车队)按车次。按车次计费**惩罚欠载**——Bi 2022(RCR, 香港112,892车次)实证 CDW 严重欠载, 支持车次计费建模。
- **部分装载**: FTL 最后一趟可半载, 处置/收益按实际吨位(修正: 原 MIP 错误禁止半载, 已修复)。

## 求解器与口径（2026-08-18 ZCode 更新）
- MixFleet 主线: PuLP 3.3.2 + CPLEX 22.1.1 教育版(0.1% 容差, best-bound 认证; Intel Ultra 9 285K / 256GB)。
- CSV 中 cpx_status 列为 PuLP 状态映射: 容差停机与限时停机均显示 Optimal; 真实终止条件以 cpx_final_gap_pct 与 cpx_time≈limit 判别(论文表 2 已按此口径呈现)。
- CBC 仅作历史 MDCA 主线兜底; 论文 Table 2-4 全部由 CPLEX 产出。


## 汇点映射与 backfill 位置（2026-08-19 修正）
- MixFleet 主线每类唯一合规汇（MIXFLEET_SINK）：earth→backfill, demolition→resource, renovation→resource。
  resource = 分选-资源化综合处置中心（先分拣再资源化/填埋分流），装修与拆除垃圾联单均固定送此；
  "未分拣严禁外运"指不得未经分拣直接倾倒，不强制经独立中转站。旧 SINK_COMPAT 仅用于 MDCA 历史主线。
- backfill（回填/弃土点）：东胜区无公开弃土场 POI（高德 2026-08-19 搜索证实），合成点置于
  罕台镇西侧边缘 (109.80, 39.84)，驾驶距离用罕台镇锚点行代理，到综合处理中心约 26km
  （符合 P01 碾红线 20km 量级；真实弃土场位于城市边缘，故此前市中心转运站代理已废弃）。
