"""
step20_reverse_stress.py — 逆压测模块（金融压力测试语言体系）

把城市韧性评估升级为金融级压力测试框架，三个子模块：

A. 逆压测 Reverse Stress Test
   - 震级连续扫描（M4.0~M8.0，0.1 步长）：精确锁定各系统 + 城市的崩溃临界震级
     （区别于现有 6 档离散扫描，逆压测是"什么情景会让城市崩"的反向搜索）
   - 震中偏移扫描（断裂带沿线 ±30km 网格）：定位最不利破裂位置 / 最安全位置

B. VaR/CVaR 尾部风险损失分布
   - 蒙特卡洛扰动（烈度衰减参数 + 易损性乘子）→ M6.0 经济损失样本分布
   - 输出：VaR95（95% 置信下损失上限）、CVaR95（尾部均值）、超越概率曲线
   - "570 亿" → "95% 置信下损失不超过 X 亿"（金融语言落地）

C. 动态传染（时变依赖权重）
   - 依赖权重随时间放大（T+0→T+72h：路断越久医疗越缺物资、危险源失控风险上升）
   - 对比固定依赖 vs 时变依赖的功能率演化与崩溃时间

输出：数据文件/stress_report.json（前端 stress 模块数据源）

方法学备注：
- 逆压测的震中偏移→功能率映射采用一阶近似（人口加权平均烈度差 × 灵敏度系数，
  同 step17_sensitivity.py 的 IntensityProxy 先例），避免逐网格重跑可达性（>30s/次）。
- VaR 损失率采用 vulnerability_matrix.py 的期望损失率（DB53/T 1475 规范），
  替代 step8 硬编码分档，更平滑且可扰动。
"""
import json
import math
import os
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

# GDAL/PROJ 环境变量（Windows 下 geopandas 必需）
from config_loader import get_config

LIB = Path("F:/anaconda/envs/zhenmai/Library/share")
os.environ.setdefault("GDAL_DATA", str(LIB / "gdal"))
os.environ.setdefault("PROJ_LIB", str(LIB / "proj"))

import geopandas as gpd  # noqa: E402

from intensity_model import IntensityModel
from vulnerability_matrix import VulnerabilityMatrix
from cascade_model import CascadeModel

# ═══════════════════════════════════════════════════════════════
# 常量与配置
# ═══════════════════════════════════════════════════════════════
SEED = 42
EPICENTER = (117.28, 31.82)  # 郯庐断裂带合肥段几何质心 (lon, lat)
DATA_DIR = Path(__file__).resolve().parent.parent / "数据文件"

# 灵敏度系数（与 step17 IntensityProxy 一致，跨震级数据回归标定）
INTENSITY_SENSITIVITY = {"transport": 0.15, "medical": 0.10,
                         "rescue": 0.10, "shelter": 0.08}
SYSTEM_KEYS = ["medical", "transport", "rescue", "shelter"]

# 时间步进（与 step16 一致）
TIME_STEPS = [0, 1, 6, 24, 72]
TIME_FACTORS = [0.0, 0.3, 0.6, 0.85, 1.0]

# 震级扫描范围（M5.0 起：与 collapse_threshold.csv 模型训练域一致，
# 避免 <M5.0 外推域产生物理荒谬的"微震即崩溃"结论）
MAG_MIN, MAG_MAX, MAG_STEP = 5.0, 8.0, 0.1


def loss_rate_step8_vectorized(intensities):
    """step8 损失率分档（与 loss_estimate 官方口径一致），向量化。

    i<5→0.0, 5≤i<7→0.05, 7≤i<8→0.20, i≥8→0.50
    """
    i = np.asarray(intensities, dtype=np.float64)
    rate = np.zeros_like(i)
    rate[(i >= 5.0) & (i < 7.0)] = 0.05
    rate[(i >= 7.0) & (i < 8.0)] = 0.20
    rate[i >= 8.0] = 0.50
    return rate


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════
def loss_rate_vectorized(intensities, vmat):
    """向量化期望损失率查表（避免逐点 Python 循环，46K 网格×500 样本提速 ~100x）。

    烈度 → 等级（同 vulnerability_matrix._float_to_grade 分界）→ 期望损失率查表。
    """
    bounds = [4.5, 5.5, 6.5, 7.5, 8.5, 9.5, 10.5, 11.5]
    grade_names = ["IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]
    idx = np.clip(np.digitize(np.asarray(intensities, dtype=np.float64), bounds),
                  0, len(grade_names) - 1)
    # 每种等级只调一次 expected_loss_rate（Python 层 9 次）
    table = np.array([vmat.expected_loss_rate(g) for g in grade_names])
    return table[idx]
def haversine_km(lon1, lat1, lon2, lat2):
    """球面距离（km），支持数组。"""
    R = 6371.0
    lon1, lat1, lon2, lat2 = map(np.radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


def yu2013_intensity(c1, c2, c3, c4, c5, M, R):
    """俞言祥 2013 烈度衰减（向量化，供蒙特卡洛扰动）。"""
    R = np.maximum(np.asarray(R, dtype=np.float64), 0.1)
    R_sat = R + c4 * np.exp(c5 * M)
    return c1 + c2 * M - c3 * np.log(R_sat)


def load_base_rates_df():
    """加载 collapse_threshold.csv 的 6 档基础功能率。"""
    df = pd.read_csv(DATA_DIR / "collapse_threshold.csv", encoding="utf-8-sig")
    df["magnitude"] = df["magnitude"].astype(float)
    return df


def interpolate_base_rates(mag, df=None):
    """对 6 档震级基础功能率插值/外推，得到任意震级的基础功能率。

    外推规则：低于 M5.0 沿相邻斜率向 1.0 推，高于 M7.5 向 0.05 推。
    """
    df = df if df is not None else load_base_rates_df()
    mags = df["magnitude"].values
    rates = {}
    for key in ["medical_ratio", "rescue_ratio", "transport_ratio", "shelter_ratio"]:
        vals = df[key].values.astype(float)
        if mag < mags[0]:
            slope = (vals[1] - vals[0]) / (mags[1] - mags[0])
            v = vals[0] + slope * (mag - mags[0])
        elif mag > mags[-1]:
            slope = (vals[-1] - vals[-2]) / (mags[-1] - mags[-2])
            v = vals[-1] + slope * (mag - mags[-1])
        else:
            v = np.interp(mag, mags, vals)
        rates[key.replace("_ratio", "")] = float(np.clip(v, 0.05, 1.0))
    return rates


# ═══════════════════════════════════════════════════════════════
# A. 逆压测
# ═══════════════════════════════════════════════════════════════
def scan_magnitude_critical(model, df):
    """震级连续扫描：锁定各系统 + 城市的崩溃临界震级。"""
    mags = np.arange(MAG_MIN, MAG_MAX + 1e-9, MAG_STEP)
    result = {
        "mags": [round(float(m), 1) for m in mags],
        "city_collapse": [],
        "system_collapse": {k: [] for k in SYSTEM_KEYS},
    }
    first_collapse = {k: None for k in SYSTEM_KEYS}
    first_collapse["city"] = None

    for m in mags:
        base = interpolate_base_rates(m, df)
        cascade = model.compute_cascade(base, propagation_factor=1.0)
        city = model.city_collapsed(cascade)
        result["city_collapse"].append(bool(city))
        for k in SYSTEM_KEYS:
            c = bool(model.judge_collapse(cascade[k], k))
            result["system_collapse"][k].append(c)
            if c and first_collapse[k] is None:
                first_collapse[k] = round(float(m), 1)
        if city and first_collapse["city"] is None:
            first_collapse["city"] = round(float(m), 1)

    result["critical_magnitudes"] = first_collapse
    # 安全边际：各系统相对当前 M6.0 场景还有多少余量（负值=已崩）
    result["margin_at_m60"] = {
        k: (round(first_collapse[k] - 6.0, 1) if first_collapse[k] else None)
        for k in first_collapse
    }
    # 口径说明：逆压测采用级联后判定（较 step10 独立判定更保守），
    # 扫描域下界（MAG_MIN）处的崩溃需结合基础功能率解读
    result["caliber_note"] = (
        f"本扫描采用级联传播后的功能率判定（口径与 step10 的独立判定不同），"
        f"扫描域为 M{MAG_MIN}~M{MAG_MAX}；临界震级等于扫描下界时表示"
        f"'该震级已崩溃，精确临界可能更低'。级联口径比单系统独立评估更早"
        f"发现崩溃——这正是跨系统依赖建模的价值：单系统评估（step10）显示"
        f"M5.0 救援功能率 41.6% 未达阈值，但级联耦合后实际已失能。"
    )
    return result


def load_grid_centroids():
    """加载 500m 网格质心（lon, lat）+ population + gdp_yi（亿元）。

    质心在投影坐标系（EPSG:4527）下计算后转回地理坐标，避免
    geographic CRS 下 centroid 的精度警告。
    """
    gdf = gpd.read_file(DATA_DIR / "grid_base.geojson")
    pop = pd.read_csv(DATA_DIR / "grid_population_gdp.csv", encoding="utf-8-sig")
    gdf_proj = gdf.to_crs(4527)
    cents = gdf_proj.geometry.centroid.to_crs(4326)
    grid = pd.DataFrame({
        "lon": cents.x.values,
        "lat": cents.y.values,
        "population": gdf["population"].astype(float).values,
        "gdp_yi": pop["gdp_yi"].astype(float).values,
    })
    return grid


def epicenter_scan(model, imodel, df, grid, half_range_km=30.0, step_km=10.0):
    """震中偏移扫描：定位最不利破裂位置。

    一阶近似：偏移震中后，人口加权平均烈度差 ΔĪ → 功能率线性偏移
    Δrate = -coef × ΔĪ × (1 - base_rate)（同 step17 代理先例）。
    """
    # 基准震中的人口加权平均烈度（M6.0）
    d0 = haversine_km(EPICENTER[0], EPICENTER[1], grid["lon"].values, grid["lat"].values)
    I0 = imodel.compute_field(6.0, d0)
    pop = grid["population"].values
    w = pop / np.maximum(pop.sum(), 1.0)
    I0_bar = float(np.sum(w * I0))

    # 候选震中网格（沿断裂带走向 N-S 为主，含 E-W 偏移）
    offsets_km = np.arange(-half_range_km, half_range_km + 1e-9, step_km)
    n = len(offsets_km)
    critical_matrix = np.full((n, n), np.nan)
    dI_matrix = np.full((n, n), np.nan)
    # 纬度 1° ≈ 111km，经度 1° ≈ 111*cos(lat) km
    lat_scale = 111.0
    lon_scale = 111.0 * math.cos(math.radians(EPICENTER[1]))

    best = None   # 最安全：烈度减弱最多（dI_bar 最小）
    worst = None  # 最危险：烈度增强最多（dI_bar 最大）

    for i, dy in enumerate(offsets_km):
        for j, dx in enumerate(offsets_km):
            if abs(dx) > 20 and abs(dy) > 20:
                continue  # 断裂带沿线主要关注 ±20km 内的破裂
            elon = EPICENTER[0] + dx / lon_scale
            elat = EPICENTER[1] + dy / lat_scale
            d_new = haversine_km(elon, elat, grid["lon"].values, grid["lat"].values)
            I_new = imodel.compute_field(6.0, d_new)
            dI_bar = float(np.sum(w * (I_new - I0)))
            dI_matrix[i, j] = dI_bar

            # 该震中下的临界震级（一阶近似扫描；注意：基准临界在扫描域下界
            # 时会被截断，dI_bar 才是连续的定位指标）
            crit = None
            for m in np.arange(MAG_MIN, MAG_MAX + 1e-9, 0.2):
                base = interpolate_base_rates(m, df)
                adj = {}
                for k in SYSTEM_KEYS:
                    adj[k] = float(np.clip(
                        base[k] - INTENSITY_SENSITIVITY[k] * dI_bar * (1 - base[k]),
                        0.05, 1.0))
                cascade = model.compute_cascade(adj, propagation_factor=1.0)
                if model.city_collapsed(cascade):
                    crit = round(float(m), 1)
                    break

            critical_matrix[i, j] = crit
            rec = {"lon": round(elon, 4), "lat": round(elat, 4),
                   "critical_mag": crit, "dI_bar": round(dI_bar, 3)}
            if worst is None or dI_bar > worst["dI_bar"]:
                worst = rec
            if best is None or dI_bar < best["dI_bar"]:
                best = rec

    # 基准震中（质心）自身的临界震级
    base_crit = None
    for m in np.arange(MAG_MIN, MAG_MAX + 1e-9, 0.1):
        base = interpolate_base_rates(m, df)
        cascade = model.compute_cascade(base, propagation_factor=1.0)
        if model.city_collapsed(cascade):
            base_crit = round(float(m), 1)
            break

    return {
        "offsets_km": [round(float(o), 1) for o in offsets_km],
        "critical_mag_matrix": critical_matrix.tolist(),
        "dI_matrix": dI_matrix.tolist(),
        "baseline_epicenter": {"lon": EPICENTER[0], "lat": EPICENTER[1],
                               "critical_mag": base_crit, "dI_bar": 0.0},
        "most_vulnerable": worst,
        "safest": best,
        "indicator_note": (
            "临界震级在扫描域下界（M5.0）处可能截断；连续定位指标为 "
            "人口加权平均烈度差 dI_bar（正=烈度增强/更危险，负=减弱/更安全）。"
        ),
    }


# ═══════════════════════════════════════════════════════════════
# B. VaR/CVaR 损失分布
# ═══════════════════════════════════════════════════════════════
def compute_loss_distribution(mag=6.0, n_samples=500):
    """蒙特卡洛扰动 → M{mag} 经济损失样本分布 → VaR/CVaR。

    损失率口径：step8 分档（与 loss_estimate_* 官方口径一致，基准≈570亿）。
    扰动源：
      1. 烈度衰减参数 c2/c3（±20% uniform，同 step17 范围）
      2. 易损性乘子 loss_mult（±20% uniform，模拟建筑易损性不确定性）
    注：损失率阶梯分档存在阈值效应，参数扰动使尾部损失显著放大，
        这正是压力测试要呈现的"极端参数组合"情景，非基准预测。
    """
    cfg = get_config()
    params = cfg.get("intensity", "yu2013", default={})
    c1, c2, c3, c4, c5 = (params.get(k, d) for k, d in
                          [("c1", 1.785), ("c2", 1.352), ("c3", 1.038),
                           ("c4", 0.017), ("c5", 0.494)])

    pop_df = pd.read_csv(DATA_DIR / "grid_population_gdp.csv", encoding="utf-8-sig")
    intensity_df = pd.read_csv(DATA_DIR / f"grid_intensity_M{mag}.csv",
                               encoding="utf-8-sig")
    # 按 cell_id 对齐（两个 CSV 行序未必一致，不能直接按行相乘）
    merged = intensity_df.merge(
        pop_df[["cell_id", "gdp_yi", "dist_to_epi_km"]], on="cell_id")
    dist_km = merged["dist_to_epi_km"].astype(float).values
    gdp = merged["gdp_yi"].astype(float).values

    # 基准锚定官方管线输出（grid_intensity 的烈度场 + 分档损失率，
    # 保证确定性损失与 loss_estimate 口径严格一致 ≈570 亿）
    I_base_official = merged["intensity"].astype(float).values
    loss_rate_base = merged["loss_rate"].astype(float).values
    deterministic_loss = float(np.sum(gdp * loss_rate_base))

    # 扰动以"参数差分"叠加到官方烈度场：I_s = I_official + ΔI(c2,c3)
    I_calc_base = yu2013_intensity(c1, c2, c3, c4, c5, mag, dist_km)

    rng = np.random.default_rng(SEED)
    samples = np.empty(n_samples, dtype=np.float64)
    BATCH = 250
    for start in range(0, n_samples, BATCH):
        end = min(start + BATCH, n_samples)
        nb = end - start
        c2_s = rng.uniform(1.082, 1.622, nb)
        c3_s = rng.uniform(0.830, 1.246, nb)
        mult_s = rng.uniform(0.8, 1.2, nb)
        for b in range(nb):
            I_calc_s = yu2013_intensity(c1, c2_s[b], c3_s[b], c4, c5, mag, dist_km)
            I_s = I_base_official + (I_calc_s - I_calc_base)
            lr = loss_rate_step8_vectorized(I_s)
            samples[start + b] = float(np.sum(gdp * lr * mult_s[b]))

    samples.sort()
    p5 = float(np.percentile(samples, 5))
    p50 = float(np.percentile(samples, 50))
    var95 = float(np.percentile(samples, 95))
    tail = samples[samples >= var95]
    cvar95 = float(tail.mean()) if len(tail) else var95
    mean_loss = float(samples.mean())

    # 直方图（40 bins，前端直接画）
    hist_counts, bin_edges = np.histogram(samples, bins=40)
    # 超越概率曲线（损失 > X 的概率，10 个分位点）
    exceed_qs = [50, 60, 70, 80, 90, 95, 97, 99, 99.5, 100.0]
    exceedance = []
    for q in exceed_qs:
        x = float(np.percentile(samples, q))
        p = float(np.mean(samples > x) * 100)
        exceedance.append({"loss_yi": round(x, 2), "exceed_prob_pct": round(p, 2)})

    return {
        "magnitude": mag,
        "n_samples": n_samples,
        "deterministic_loss_yi": round(deterministic_loss, 2),
        "mean_loss_yi": round(mean_loss, 2),
        "median_loss_yi": round(p50, 2),
        "p5_loss_yi": round(p5, 2),
        "var95_yi": round(var95, 2),
        "cvar95_yi": round(cvar95, 2),
        "loss_histogram": {
            "bins": [round(float(e), 2) for e in bin_edges],
            "counts": hist_counts.tolist(),
        },
        "exceedance_curve": exceedance,
        "insurance_implied": {
            "premium_baseline": round(var95 * 0.02, 2),   # 巨灾保险基准费率 2%
            "reserve_target": round(cvar95, 2),           # 风险准备金目标 = CVaR
        },
    }


# ═══════════════════════════════════════════════════════════════
# C. 动态传染（时变依赖权重）
# ═══════════════════════════════════════════════════════════════
def time_varying_dependency(model, df, mags=(5.0, 5.5, 6.0)):
    """时变依赖权重 vs 固定依赖：功能率演化对比（支持多震级）。

    时变规则（物理直觉，随灾后时间恶化）：
      - 医疗对交通依赖 0.45 → 0.60（路断越久物资越缺）
      - 避难对救援依赖 0.52 → 0.70（危险源失控风险上升）
      - 救援对医疗依赖 0.20 → 0.28（接收伤员能力恶化）
      - 避难对医疗依赖 0.38 → 0.46，救援对交通 0.55 → 0.62
    """
    # 时变依赖：T+0 基准 → T+72h 放大
    dep_evol = {
        "medical_transport": [0.45, 0.47, 0.50, 0.55, 0.60],
        "shelter_rescue":    [0.52, 0.55, 0.60, 0.65, 0.70],
        "rescue_medical":    [0.20, 0.21, 0.23, 0.26, 0.28],
        "shelter_medical":   [0.38, 0.39, 0.41, 0.44, 0.46],
        "rescue_transport":  [0.55, 0.56, 0.58, 0.60, 0.62],
        "shelter_transport": [0.20, 0.21, 0.22, 0.23, 0.24],
    }
    # 其余依赖保持基准值
    dep0 = model.dep

    def build_dynamic_dep(t_idx):
        d = {k: dict(v) for k, v in dep0.items()}
        d["medical"]["transport"] = dep_evol["medical_transport"][t_idx]
        d["shelter"]["rescue"] = dep_evol["shelter_rescue"][t_idx]
        d["rescue"]["medical"] = dep_evol["rescue_medical"][t_idx]
        d["shelter"]["medical"] = dep_evol["shelter_medical"][t_idx]
        d["rescue"]["transport"] = dep_evol["rescue_transport"][t_idx]
        d["shelter"]["transport"] = dep_evol["shelter_transport"][t_idx]
        return d

    fixed_model = CascadeModel()  # 固定依赖（config 基准）
    thresholds = fixed_model.thresholds

    def first_collapse_time(series):
        """每个系统的首次崩溃时间（dict）。"""
        result = {}
        for k in SYSTEM_KEYS:
            result[k] = None
            for i, t in enumerate(TIME_STEPS):
                if series[k][i] < thresholds.get(k, 0.3):
                    result[k] = t
                    break
        city = min((v for v in result.values() if v is not None), default=None)
        result["city"] = city
        return result

    def run_one(mag):
        base = interpolate_base_rates(mag, df)
        fixed_series = {k: [] for k in SYSTEM_KEYS}
        dynamic_series = {k: [] for k in SYSTEM_KEYS}
        for t_idx, (t, factor) in enumerate(zip(TIME_STEPS, TIME_FACTORS)):
            cf = fixed_model.compute_cascade(base, propagation_factor=factor)
            dyn_model = CascadeModel(
                params_override={"dependency_matrix": build_dynamic_dep(t_idx)})
            cd = dyn_model.compute_cascade(base, propagation_factor=factor)
            for k in SYSTEM_KEYS:
                fixed_series[k].append(round(cf[k], 4))
                dynamic_series[k].append(round(cd[k], 4))
        # 依赖强化导致的额外功能率下降（T+72h，fixed vs dynamic）
        extra_drop = {
            k: round(fixed_series[k][-1] - dynamic_series[k][-1], 4)
            for k in SYSTEM_KEYS
        }
        return {
            "fixed_dependency": {"systems": fixed_series,
                                 "collapse_time_by_system": first_collapse_time(fixed_series)},
            "dynamic_dependency": {"systems": dynamic_series,
                                   "collapse_time_by_system": first_collapse_time(dynamic_series)},
            "reinforcement_extra_drop": extra_drop,
        }

    by_mag = {str(m): run_one(m) for m in mags}
    # 高亮震级：某系统"固定不崩但时变崩" 或 首崩时间被提前
    highlight = None
    for m in mags:
        r = by_mag[str(m)]
        fct = r["fixed_dependency"]["collapse_time_by_system"]
        dct = r["dynamic_dependency"]["collapse_time_by_system"]
        for k in SYSTEM_KEYS:
            if fct[k] is None and dct[k] is not None:
                highlight = str(m)
                break
            if fct[k] is not None and dct[k] is not None and dct[k] < fct[k]:
                highlight = str(m)
                break
        if highlight:
            break
    if highlight is None:
        for m in mags:
            if max(by_mag[str(m)]["reinforcement_extra_drop"].values()) >= 0.05:
                highlight = str(m)
                break
    if highlight is None:
        highlight = str(mags[-1])

    return {
        "magnitudes": [float(m) for m in mags],
        "time_steps": TIME_STEPS,
        "time_labels": ["T+0", "T+1h", "T+6h", "T+24h", "T+72h"],
        "dependency_evolution": dep_evol,
        "by_magnitude": by_mag,
        "highlight_magnitude": highlight,
        "interpretation": (
            "时变依赖（灾后依赖强化）使救援/避难系统功能率加速衰减，"
            "崩溃时间可能提前——对比固定/时变两组曲线可量化'依赖强化'对"
            "韧性评估的影响。"
        ),
    }


# ═══════════════════════════════════════════════════════════════
# 主流程 + 验证
# ═══════════════════════════════════════════════════════════════
def main():
    print("=" * 70)
    print("逆压测模块 (Reverse Stress Test)")
    print("=" * 70)

    model = CascadeModel()
    imodel = IntensityModel()
    df = load_base_rates_df()

    # A. 逆压测：震级扫描
    print(f"\n[A] 震级连续扫描（M{MAG_MIN}~M{MAG_MAX}）...")
    mag_scan = scan_magnitude_critical(model, df)
    print("  临界震级:", mag_scan["critical_magnitudes"])

    # A2. 逆压测：震中偏移扫描
    print("\n[A2] 震中偏移扫描（断裂带沿线 ±30km）...")
    grid = load_grid_centroids()
    epi_scan = epicenter_scan(model, imodel, df, grid)
    print("  最不利破裂位置:", epi_scan["most_vulnerable"])

    # B. VaR/CVaR
    print("\n[B] 蒙特卡洛损失分布（500 样本）...")
    var = compute_loss_distribution(mag=6.0, n_samples=500)
    print(f"  确定性损失: {var['deterministic_loss_yi']} 亿 | "
          f"VaR95: {var['var95_yi']} 亿 | CVaR95: {var['cvar95_yi']} 亿")

    # C. 动态传染
    print("\n[C] 动态传染（时变依赖）...")
    contagion = time_varying_dependency(model, df, mags=[5.0, 5.5, 6.0])
    for m, r in contagion["by_magnitude"].items():
        fct = r["fixed_dependency"]["collapse_time_by_system"]["city"]
        dct = r["dynamic_dependency"]["collapse_time_by_system"]["city"]
        drop = max(r["reinforcement_extra_drop"].values())
        print(f"  M{m}: 城市首崩 固定{fct}h/时变{dct}h | "
              f"依赖强化最大额外下降 {drop}")
    print(f"  高亮震级: M{contagion['highlight_magnitude']}")

    report = {
        "report_meta": {
            "module": "step20_reverse_stress",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "purpose": "金融压力测试语言体系：逆压测 + VaR/CVaR + 动态传染",
            "seed": SEED,
            "framework": "Reverse Stress Test / VaR-CVaR / Dynamic Contagion",
        },
        "reverse_stress": {"magnitude_scan": mag_scan, "epicenter_scan": epi_scan},
        "var_cvar": var,
        "dynamic_contagion": contagion,
    }

    # NaN → null：Python json 默认写出 NaN（非标准 JSON），浏览器 JSON.parse 会拒绝
    def clean_nan(obj):
        if isinstance(obj, float) and math.isnan(obj):
            return None
        if isinstance(obj, list):
            return [clean_nan(x) for x in obj]
        if isinstance(obj, dict):
            return {k: clean_nan(v) for k, v in obj.items()}
        return obj

    out_path = DATA_DIR / "stress_report.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(clean_nan(report), f, ensure_ascii=False, indent=2)
    print(f"\n报告已保存: {out_path}")

    ok = verify(report)
    print("\n[OK] 全链路自检通过" if ok else "\n[FAIL] 自检存在失败项")
    return ok


def verify(report):
    """验证检查（各模块输出合理性与单调性）。"""
    reasons = []

    # A. 逆压测
    ms = report["reverse_stress"]["magnitude_scan"]
    crit = ms["critical_magnitudes"]
    if crit["city"] is None:
        reasons.append("城市临界震级缺失")
    else:
        if not (4.0 <= crit["city"] <= 8.0):
            reasons.append(f"城市临界震级越界: {crit['city']}")
        # 单调性：城市崩溃标志随震级从 False→True（升序排列应等于自身）
        cc = ms["city_collapse"]
        if cc != sorted(cc):
            reasons.append("城市崩溃标志不随震级单调")
    # 各系统临界 ≤ 城市临界（城市 = 任一系统崩）
    for k in SYSTEM_KEYS:
        if crit.get(k) is not None and crit["city"] is not None:
            if crit[k] < crit["city"] - 1e-9:
                reasons.append(f"系统{k}临界({crit[k]})应 ≥ 城市临界({crit['city']})前")

    # 震中扫描
    es = report["reverse_stress"]["epicenter_scan"]
    mv = es["most_vulnerable"]
    base_c = es["baseline_epicenter"]["critical_mag"]
    if mv is None or base_c is None:
        reasons.append("震中扫描关键数据缺失")
    else:
        # 最不利位置的烈度差应 ≥ 基准（0）——即烈度增强
        if mv["dI_bar"] < -1e-9:
            reasons.append("最不利位置 dI_bar 应 ≥ 0（烈度增强）")
        # dI_matrix 需有非 NaN 值且与 offsets 维度一致
        n = len(es["offsets_km"])
        dmat = np.array(es["dI_matrix"])
        if dmat.shape != (n, n) or not np.any(~np.isnan(dmat)):
            reasons.append("dI_matrix 维度或有效值异常")

    # B. VaR/CVaR
    var = report["var_cvar"]
    if not (var["p5_loss_yi"] <= var["median_loss_yi"] <= var["var95_yi"] <= var["cvar95_yi"] + 1e-9):
        reasons.append("损失分位数排序异常 (p5≤p50≤VaR95≤CVaR95)")
    if var["deterministic_loss_yi"] <= 0:
        reasons.append("确定性损失非正")
    if len(var["loss_histogram"]["counts"]) != 40:
        reasons.append("直方图 bin 数异常")

    # C. 动态传染
    dc = report["dynamic_contagion"]
    for m_str, r in dc["by_magnitude"].items():
        fd = r["fixed_dependency"]["systems"]
        dd = r["dynamic_dependency"]["systems"]
        for k in SYSTEM_KEYS:
            if dd[k] != sorted(dd[k], reverse=True):
                reasons.append(f"时变依赖 M{m_str} {k} 功能率不单调下降")
            for i in range(len(dc["time_steps"])):
                if dd[k][i] > fd[k][i] + 1e-9:
                    reasons.append(f"时变依赖 M{m_str} {k} T+{dc['time_steps'][i]}h 应 ≤ 固定依赖")
        for k in SYSTEM_KEYS:
            if r["reinforcement_extra_drop"][k] < -1e-9:
                reasons.append(f"M{m_str} {k} 依赖强化额外下降应为非负")
    if dc["highlight_magnitude"] not in dc["by_magnitude"]:
        reasons.append("高亮震级不在结果集合中")

    for r in reasons:
        print(f"  [FAIL] {r}")
    return len(reasons) == 0


if __name__ == "__main__":
    main()
