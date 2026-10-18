# Parameter provenance — CDW-MixFleet replication package

Scope: every parameter that enters the **MixFleet** model and the numbers reported in the
manuscript. Entries cite one of three evidence levels:

- **[L] literature / regulation-cited** — a specific published or regulatory source;
- **[C] case-informed** — calibrated to aggregate statistics of the district's public
  construction-waste filing records (2023–2025, ~80 anonymous aggregate entries: 100% of
  records fix the disposal destination and hauling corridor; earth-class bulk streams
  dominate filed volume; project-scale median ≈ 10,000 m³). The raw ledger is **not**
  distributed; only these aggregates enter the paper.
- **[A] modeling assumption** — a research setting, disclosed as such and, where it
  matters, sensitivity-tested in the paper (range given).

| Parameter | Value (base) | Level | Source / note |
|---|---|---|---|
| Waste classes (earth / demolition / renovation) | three, class-licensed | [L] | Beijing Order 293 (2023) class scheme; Guangdong Reg. 2022 licensing |
| Night window H | 8 h (22:00–06:00) | [L] | municipal truck-access rules |
| Truck capacity W | 15 t (≈12–15 m³ dump truck) | [L] | carrier fleet norm (P05 practice survey) |
| Route slots T | 8 per vehicle | [A] | variable-space device; non-binding in all mixed-mode plans (paper §3.2) |
| Mean cycle speed | 35 km/h | [A] | urban night traffic; §5.1 |
| Load/unload time | 0.5 h per full-load equivalent | [A] | per-tonne handling in base model; per-stop 0/6/12 min and symmetric FTL 0.5 h tested (§5.6, §5.9) |
| Fixed dispatch fee F_trip | 400 CNY/trip | [L] | Yu2025 (Chengdu carrier data: 750 CNY/truck-day) converted; sensitivity 200–600 (§5.6) |
| Distance tariff | 3.9 CNY/truck-km | [L] | Yu2025 (diesel cost basis) |
| Shortage penalty π | 150 CNY/t | [C]+[L] | contractual deferral charges in carrier practice, cross-checked against penalty magnitudes in Wu2025; sensitivity 50–500 (§5.6) |
| Sink fees (backfill / resource / landfill / transfer) | 20 / 45 / 30 / 12 CNY/t | [A] | case-informed tariff band; not varied (§6 discusses tariff design) |
| Sink revenues (backfill / resource) | 8 / 60 CNY/t | [A] | recycled-product prices, case band |
| Class–sink mapping | earth→backfill, demolition→resource, renovation→resource | [L] | manifest-fixed compliance routing |
| FTL tonnage range | 40–600 t per site | [C] | filing-record bulk-stream scale (median project ≈10,000 m³ over a project life; per-night draws scaled accordingly) |
| LTL tonnage range | 5–45 t per site | [C] | filing-record small-stream tail |
| Class composition of draws | 60 / 25 / 15% (earth/demolition/renovation) | [C] | aggregate share of filed volume (~5/6 bulk) |
| Demand-volume law | lognormal, σ=1.1 | [A] | right-skew fitted to project-scale spread |
| Fleet sizes (S/M/L/X) | per `results_reference/calibration_proposal.csv` | [A] | calibrated to 75–80% per-class night-hour utilization |
| XL stress instance | 24 trucks, seed 7 | [A] | uncalibrated scale probe; seed-42 draw rejected for a capacity confound (paper §5.1) |
| Driving-distance matrix | 87/90 anchor pairs Amap API; 3 intra-city pairs × 1.30 detour | [C] | queried 2026; © Amap. Access leg straight-line from sub-district anchor |
| Road network (case map) | OpenStreetMap extract | [L] | © OpenStreetMap contributors (ODbL) |

Legacy parameters of the earlier network-design study (transfer throughput, recycling
quotas, per-tonne-km unit transport) are **not** used by the MixFleet model and are
retained in `src/params.py` only for backward compatibility.

Literature keys refer to the manuscript's reference list: Bi et al. (2022) (FTL-like
underloading, 112,892 movements), Yu et al. (2025) (disposal/recycling economics and
carrier tariff levels), Wu et al. (2025) (penalty magnitudes), Shao et al. (2026)
(demand-responsive skip planning). Regulatory instruments: Beijing Order No. 293 (2023)
on construction-waste classification; Guangdong Regulation (2022) on class-licensed
haulage; district manifest rules (2024) fixing destination and corridor per record.

Seed policy: search seed 42 everywhere except the XL instance's demand realization
(seed 7) and the ILS baseline's XL search run (seed 7), as stated in the paper's Table 6
caption.
