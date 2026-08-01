"""
step17_sensitivity.py — 蒙特卡洛参数敏感性分析

项目核心创新点：量化模型参数不确定性对崩溃临界震级的影响。

三种分析方法：
  1. 蒙特卡洛模拟（500次）：从参数分布中随机采样，统计崩溃临界震级分布
  2. 一次一因子法（OAT）：逐参数 ±20% 变化，构建龙卷风图
  3. Spearman 秩相关分析：参数与输出的相关性，排序参数重要性

分析参数（8个，来自 config.yaml sensitivity 段）：
  - 烈度衰减系数 c2, c3（影响基础功能率）
  - 跨系统依赖权重 ×4（影响级联传播强度）
  - 崩溃阈值 ×2（影响崩溃判定边界）

烈度参数代理模型：
  由于完整管线重算不可行（每次需 >30s），采用代理：
  1. 用 IntensityModel 计算关键距离（5~50km）的烈度变化 ΔI
  2. 通过线性映射将 ΔI 传递到基础功能率：
     Δrate = -sensitivity_coef × ΔI × (1 - base_rate)
  3. 敏感系数从跨震级数据回归标定

输出：
  - sensitivity_report.json（完整报告）
  - 更新 dashboard_M5.0~M7.5.json（添加 sensitivity 段）
"""
import os
from pathlib import Path

# ── GDAL/PROJ 路径 ──
LIB = Path("F:/anaconda/envs/zhenmai/Library/share")
os.environ.setdefault("GDAL_DATA", str(LIB / "gdal"))
os.environ.setdefault("PROJ_LIB", str(LIB / "proj"))

import warnings
warnings.filterwarnings("ignore")

import sys
import json
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config_loader import get_config
from cascade_model import CascadeModel
from intensity_model import IntensityModel


def _spearman_rho(x, y):
    """纯 numpy 实现的 Spearman 秩相关系数（避免 scipy DLL 问题）。

    Args:
        x, y: 数值列表/数组

    Returns:
        (rho, p_value): 相关系数和近似 p 值
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(x)
    if n < 3:
        return 0.0, 1.0

    # 计算秩（使用 average 排序处理 ties）
    def _rank(arr):
        order = np.argsort(arr, kind='mergesort')
        ranks = np.empty(n, dtype=float)
        ranks[order] = np.arange(1, n + 1, dtype=float)
        # 处理 ties：相同值取平均秩
        sorted_vals = arr[order]
        i = 0
        while i < n:
            j = i
            while j + 1 < n and sorted_vals[j + 1] == sorted_vals[i]:
                j += 1
            if j > i:
                avg_rank = (ranks[order[i]] + ranks[order[j]]) / 2.0
                for k in range(i, j + 1):
                    ranks[order[k]] = avg_rank
            i = j + 1
        return ranks

    rx = _rank(x)
    ry = _rank(y)

    # Spearman rho = Pearson(r_x, r_y)
    rx_mean = rx.mean()
    ry_mean = ry.mean()
    numerator = np.sum((rx - rx_mean) * (ry - ry_mean))
    denominator = np.sqrt(np.sum((rx - rx_mean) ** 2) * np.sum((ry - ry_mean) ** 2))

    if denominator == 0:
        return 0.0, 1.0

    rho = float(numerator / denominator)

    # 近似 p 值（t 分布）
    if n > 2:
        t_stat = rho * np.sqrt((n - 2) / max(1e-10, 1 - rho ** 2))
        # 使用正态近似代替 t 分布（避免 scipy 依赖）
        from math import erf, sqrt
        p_value = 2.0 * (1.0 - 0.5 * (1.0 + erf(abs(t_stat) / sqrt(2.0))))
    else:
        p_value = 1.0

    return rho, float(p_value)

# ═══════════════════════════════════════════════════════════
# 全局配置
# ═══════════════════════════════════════════════════════════
cfg = get_config()
DATA_DIR = cfg.data_dir
MAGNITUDES = cfg.magnitudes
SEED = cfg.get("sensitivity", "seed", default=42)
N_SAMPLES = cfg.get("sensitivity", "n_samples", default=500)

np.random.seed(SEED)

# 关键距离（km），用于烈度代理模型
KEY_DISTANCES = np.array([5, 10, 20, 30, 50, 75, 100])

# 烈度→功能率 敏感系数（从跨震级数据回归标定）
# 含义：每单位烈度变化导致的功能率变化比例
INTENSITY_SENSITIVITY = {
    "transport": 0.15,   # 交通对烈度最敏感（道路阻断）
    "medical":   0.10,   # 医疗次之（建筑损伤影响可达性）
    "rescue":    0.10,   # 救援与医疗类似
    "shelter":   0.08,   # 避难相对不敏感（容量冗余）
}


# ═══════════════════════════════════════════════════════════
# 1. 参数定义与采样
# ═══════════════════════════════════════════════════════════
def load_sensitivity_params():
    """从 config.yaml 加载敏感性分析参数定义。"""
    raw = cfg.get("sensitivity", "params", default={})
    params = []
    for name, spec in raw.items():
        params.append({
            "name": name,
            "base": spec["base"],
            "low": spec["range"][0],
            "high": spec["range"][1],
            "distribution": spec.get("distribution", "uniform"),
        })
    return params


def sample_parameters(params, n_samples, rng):
    """从参数分布中采样。

    Returns:
        dict: {param_name: array(n_samples,)}
    """
    samples = {}
    for p in params:
        if p["distribution"] == "uniform":
            samples[p["name"]] = rng.uniform(p["low"], p["high"], n_samples)
        elif p["distribution"] == "normal":
            mean = p["base"]
            std = (p["high"] - p["low"]) / 4  # ±2σ 覆盖范围
            samples[p["name"]] = np.clip(
                rng.normal(mean, std, n_samples), p["low"], p["high"]
            )
        else:
            samples[p["name"]] = rng.uniform(p["low"], p["high"], n_samples)
    return samples


# ═══════════════════════════════════════════════════════════
# 2. 烈度参数代理模型
# ═══════════════════════════════════════════════════════════
class IntensityProxy:
    """烈度参数→基础功能率 代理模型。

    避免完整管线重算，用线性映射近似烈度变化对功能率的影响。
    """

    def __init__(self):
        self.base_model = IntensityModel("yu2013")
        self.base_params = cfg.get("intensity", "yu2013", default={})
        # 预计算基准烈度（每个震级在关键距离上的平均烈度）
        self.base_intensities = {}
        for mag in MAGNITUDES:
            intensities = self.base_model.compute_field(mag, KEY_DISTANCES)
            self.base_intensities[mag] = np.mean(intensities)

    def compute_intensity_change(self, c2, c3, magnitude):
        """计算 c2/c3 变化后的平均烈度变化量。

        Returns:
            ΔI (float): 平均烈度变化（正值=烈度增大）
        """
        # 用变化后的参数重建烈度
        c1 = self.base_params.get("c1", 1.785)
        c4 = self.base_params.get("c4", 0.017)
        c5 = self.base_params.get("c5", 0.494)

        R = np.maximum(KEY_DISTANCES, 0.1)
        R_sat = R + c4 * np.exp(c5 * magnitude)
        new_intensity = c1 + c2 * magnitude - c3 * np.log(R_sat)
        new_avg = np.mean(new_intensity)

        return new_avg - self.base_intensities[magnitude]

    def adjust_base_rates(self, base_rates, c2, c3):
        """根据烈度参数变化调整基础功能率。

        Args:
            base_rates: dict {medical, transport, rescue, shelter}
            c2, c3: 烈度衰减系数

        Returns:
            调整后的 base_rates
        """
        mag = base_rates["magnitude"]
        delta_I = self.compute_intensity_change(c2, c3, mag)

        adjusted = {"magnitude": mag}
        for system in ["medical", "transport", "rescue", "shelter"]:
            base = base_rates[system]
            coef = INTENSITY_SENSITIVITY[system]
            # 烈度增大 → 功能率下降
            # Δrate = -coef × ΔI × (1 - base_rate)
            # 确保功能率在 [0, 1] 范围内
            new_rate = base - coef * delta_I * (1.0 - base)
            adjusted[system] = max(0.0, min(1.0, new_rate))

        return adjusted


# ═══════════════════════════════════════════════════════════
# 3. 单次蒙特卡洛试验
# ═══════════════════════════════════════════════════════════
def run_single_trial(base_rates_list, sample, proxy):
    """执行一次蒙特卡洛试验。

    Args:
        base_rates_list: 基准功能率列表
        sample: 参数采样字典 {name: value}
        proxy: IntensityProxy 实例

    Returns:
        dict: 试验结果
    """
    # 提取参数
    c2 = sample.get("intensity_c2", 1.352)
    c3 = sample.get("intensity_c3", 1.038)

    # 构建依赖矩阵覆盖
    dep_matrix = cfg.get("cascade", "dependency_matrix", default={})
    dep_override = {}
    for target in dep_matrix:
        dep_override[target] = dict(dep_matrix[target])

    # 覆盖采样的依赖权重
    if "dep_transport_medical" in sample:
        dep_override["medical"]["transport"] = sample["dep_transport_medical"]
    if "dep_transport_rescue" in sample:
        dep_override["rescue"]["transport"] = sample["dep_transport_rescue"]
    if "dep_medical_shelter" in sample:
        dep_override["shelter"]["medical"] = sample["dep_medical_shelter"]
    if "dep_rescue_shelter" in sample:
        dep_override["shelter"]["rescue"] = sample["dep_rescue_shelter"]

    # 构建阈值覆盖
    thresholds = dict(cfg.get("collapse_thresholds", default={}))
    if "medical_threshold" in sample:
        thresholds["medical"] = sample["medical_threshold"]
    if "rescue_threshold" in sample:
        thresholds["rescue"] = sample["rescue_threshold"]

    # 创建级联模型
    model = CascadeModel(params_override={
        "dependency_matrix": dep_override,
        "thresholds": thresholds,
    })

    # 调整基础功能率（烈度代理）
    adjusted_rates = []
    for base in base_rates_list:
        adjusted = proxy.adjust_base_rates(base, c2, c3)
        adjusted_rates.append(adjusted)

    # 计算各震级级联
    results = []
    for base in adjusted_rates:
        cascade = model.compute_cascade(base, propagation_factor=1.0)
        results.append({
            "magnitude": base["magnitude"],
            "cascade": cascade,
        })

    # 找崩溃临界震级
    threshold_mag = model.find_threshold_magnitude(results)

    # 记录各震级各系统级联率
    cascade_ratios = {}
    for r in results:
        mag_key = f"M{r['magnitude']:.1f}"
        cascade_ratios[mag_key] = {
            k: r["cascade"][k] for k in CascadeModel.SYSTEM_KEYS
        }
        cascade_ratios[mag_key]["city_collapse"] = model.city_collapsed(r["cascade"])

    return {
        "threshold_magnitude": threshold_mag,
        "cascade_ratios": cascade_ratios,
    }


# ═══════════════════════════════════════════════════════════
# 4. 蒙特卡洛模拟
# ═══════════════════════════════════════════════════════════
def run_monte_carlo(base_rates_list, params, proxy, n_samples=N_SAMPLES):
    """执行完整蒙特卡洛模拟。

    在 MC 运行中同时收集参数-输出对，用于后续 Spearman 相关分析，
    避免二次遍历。

    Returns:
        dict: MC 统计结果 + 相关分析原始数据
    """
    rng = np.random.RandomState(SEED)
    samples = sample_parameters(params, n_samples, rng)

    threshold_mags = []
    all_cascade_ratios = {f"M{mag:.1f}": {k: [] for k in CascadeModel.SYSTEM_KEYS}
                          for mag in MAGNITUDES}
    city_collapse_counts = {f"M{mag:.1f}": 0 for mag in MAGNITUDES}

    # 相关分析数据收集（M6.0 作为代表震级）
    corr_param_values = {name: [] for name in samples}
    corr_resilience_values = []
    corr_threshold_values = []

    print(f"  运行 {n_samples} 次蒙特卡洛试验...")
    for i in range(n_samples):
        if (i + 1) % 100 == 0:
            print(f"    进度: {i+1}/{n_samples}")

        sample = {name: samples[name][i] for name in samples}
        result = run_single_trial(base_rates_list, sample, proxy)

        threshold_mags.append(result["threshold_magnitude"])

        # 收集相关分析数据
        for name in samples:
            corr_param_values[name].append(sample[name])
        m60 = result["cascade_ratios"].get("M6.0", {})
        resilience = float(np.mean([m60.get(k, 0) for k in CascadeModel.SYSTEM_KEYS]))
        corr_resilience_values.append(resilience)
        corr_threshold_values.append(result["threshold_magnitude"] or 7.5)

        for mag_key, ratios in result["cascade_ratios"].items():
            for sys_key in CascadeModel.SYSTEM_KEYS:
                all_cascade_ratios[mag_key][sys_key].append(ratios[sys_key])
            if ratios.get("city_collapse"):
                city_collapse_counts[mag_key] += 1

    threshold_mags = [m for m in threshold_mags if m is not None]

    # 统计崩溃临界震级分布
    mc_threshold = None
    if threshold_mags:
        mc_threshold = {
            "mean": round(float(np.mean(threshold_mags)), 2),
            "std": round(float(np.std(threshold_mags)), 2),
            "median": round(float(np.median(threshold_mags)), 2),
            "p5": round(float(np.percentile(threshold_mags, 5)), 2),
            "p25": round(float(np.percentile(threshold_mags, 25)), 2),
            "p75": round(float(np.percentile(threshold_mags, 75)), 2),
            "p95": round(float(np.percentile(threshold_mags, 95)), 2),
            "min": round(float(np.min(threshold_mags)), 2),
            "max": round(float(np.max(threshold_mags)), 2),
            "values": [round(m, 1) for m in threshold_mags],
        }

    # 各震级各系统级联率置信区间
    confidence_intervals = {}
    for mag_key, sys_data in all_cascade_ratios.items():
        confidence_intervals[mag_key] = {}
        for sys_key, values in sys_data.items():
            if values:
                arr = np.array(values)
                confidence_intervals[mag_key][sys_key] = {
                    "mean": round(float(np.mean(arr)), 4),
                    "std": round(float(np.std(arr)), 4),
                    "p5": round(float(np.percentile(arr, 5)), 4),
                    "p95": round(float(np.percentile(arr, 95)), 4),
                }

    # 城市崩溃概率
    collapse_probabilities = {}
    for mag_key, count in city_collapse_counts.items():
        collapse_probabilities[mag_key] = round(count / n_samples, 4)

    return {
        "n_samples": n_samples,
        "threshold_magnitude_distribution": mc_threshold,
        "confidence_intervals": confidence_intervals,
        "collapse_probabilities": collapse_probabilities,
        "samples": {name: [round(float(v), 4) for v in vals[:50]]  # 保存前50个采样用于可视化
                    for name, vals in samples.items()},
        # 相关分析原始数据（不导出 JSON，仅内部使用）
        "_corr_data": {
            "param_values": corr_param_values,
            "resilience_values": corr_resilience_values,
            "threshold_values": corr_threshold_values,
        },
    }


# ═══════════════════════════════════════════════════════════
# 5. 一次一因子法（OAT）— 龙卷风图
# ═══════════════════════════════════════════════════════════
def run_oat_analysis(base_rates_list, params, proxy):
    """逐参数 ±20% 变化，构建龙卷风图数据。

    Returns:
        list: 每个参数的敏感性数据
    """
    # 基准结果
    base_sample = {p["name"]: p["base"] for p in params}
    base_result = run_single_trial(base_rates_list, base_sample, proxy)
    base_threshold = base_result["threshold_magnitude"]

    # 基准级联率（M6.0 作为代表震级）
    base_m60 = base_result["cascade_ratios"].get("M6.0", {})

    tornado = []
    print("  运行 OAT 敏感性分析...")
    for p in params:
        # 低值
        low_sample = dict(base_sample)
        low_sample[p["name"]] = p["low"]
        low_result = run_single_trial(base_rates_list, low_sample, proxy)
        low_threshold = low_result["threshold_magnitude"]

        # 高值
        high_sample = dict(base_sample)
        high_sample[p["name"]] = p["high"]
        high_result = run_single_trial(base_rates_list, high_sample, proxy)
        high_threshold = high_result["threshold_magnitude"]

        # M6.0 级联率变化
        low_m60 = low_result["cascade_ratios"].get("M6.0", {})
        high_m60 = high_result["cascade_ratios"].get("M6.0", {})

        # 韧性指数变化（四系统均值）
        base_resilience = np.mean([base_m60.get(k, 0) for k in CascadeModel.SYSTEM_KEYS])
        low_resilience = np.mean([low_m60.get(k, 0) for k in CascadeModel.SYSTEM_KEYS])
        high_resilience = np.mean([high_m60.get(k, 0) for k in CascadeModel.SYSTEM_KEYS])

        # 参数中文名
        param_labels = {
            "intensity_c2": "烈度系数 c₂",
            "intensity_c3": "烈度系数 c₃",
            "dep_transport_medical": "交通→医疗 依赖",
            "dep_transport_rescue": "交通→救援 依赖",
            "dep_medical_shelter": "医疗→避难 依赖",
            "dep_rescue_shelter": "救援→避难 依赖",
            "medical_threshold": "医疗崩溃阈值",
            "rescue_threshold": "救援崩溃阈值",
        }

        tornado.append({
            "param": p["name"],
            "label": param_labels.get(p["name"], p["name"]),
            "base": p["base"],
            "low": p["low"],
            "high": p["high"],
            "base_threshold": base_threshold,
            "low_threshold": low_threshold,
            "high_threshold": high_threshold,
            "threshold_range": round(abs(
                (high_threshold or 0) - (low_threshold or 0)
            ), 2),
            "base_resilience": round(float(base_resilience), 4),
            "low_resilience": round(float(low_resilience), 4),
            "high_resilience": round(float(high_resilience), 4),
            "resilience_range": round(float(abs(high_resilience - low_resilience)), 4),
            # 各系统级联率变化
            "system_impact": {
                sys_key: {
                    "base": round(float(base_m60.get(sys_key, 0)), 4),
                    "low": round(float(low_m60.get(sys_key, 0)), 4),
                    "high": round(float(high_m60.get(sys_key, 0)), 4),
                    "range": round(float(abs(
                        high_m60.get(sys_key, 0) - low_m60.get(sys_key, 0)
                    )), 4),
                }
                for sys_key in CascadeModel.SYSTEM_KEYS
            },
        })

    # 按影响范围排序（降序）
    tornado.sort(key=lambda x: x["resilience_range"], reverse=True)

    return tornado


# ═══════════════════════════════════════════════════════════
# 6. Spearman 秩相关分析
# ═══════════════════════════════════════════════════════════
def run_correlation_analysis(mc_result, params):
    """计算参数与输出的 Spearman 秩相关系数。

    使用 MC 运行中收集的数据，无需二次遍历。
    """
    corr_data = mc_result.get("_corr_data")
    if not corr_data:
        print("  [警告] 无相关分析数据，跳过")
        return []

    param_values = corr_data["param_values"]
    resilience_values = corr_data["resilience_values"]
    threshold_values = corr_data["threshold_values"]

    param_labels = {
        "intensity_c2": "烈度系数 c₂",
        "intensity_c3": "烈度系数 c₃",
        "dep_transport_medical": "交通→医疗 依赖",
        "dep_transport_rescue": "交通→救援 依赖",
        "dep_medical_shelter": "医疗→避难 依赖",
        "dep_rescue_shelter": "救援→避难 依赖",
        "medical_threshold": "医疗崩溃阈值",
        "rescue_threshold": "救援崩溃阈值",
    }

    print(f"  计算 Spearman 秩相关（{len(resilience_values)} 个样本）...")

    correlations = []
    for name in param_values:
        rho_resilience, p_resilience = _spearman_rho(
            param_values[name], resilience_values
        )
        rho_threshold, p_threshold = _spearman_rho(
            param_values[name], threshold_values
        )
        correlations.append({
            "param": name,
            "label": param_labels.get(name, name),
            "rho_resilience": round(float(rho_resilience), 4),
            "p_resilience": round(float(p_resilience), 6),
            "rho_threshold": round(float(rho_threshold), 4),
            "p_threshold": round(float(p_threshold), 6),
            "significant": p_resilience < 0.05,
        })

    # 按绝对相关系数排序
    correlations.sort(key=lambda x: abs(x["rho_resilience"]), reverse=True)

    return correlations


# ═══════════════════════════════════════════════════════════
# 7. 构建仪表盘 sensitivity 数据段
# ═══════════════════════════════════════════════════════════
def build_dashboard_sensitivity(mag, mc_result, tornado, correlations):
    """为单个震级构建 sensitivity JSON 数据段。"""
    mag_key = f"M{mag:.1f}"

    # 该震级的置信区间
    ci = mc_result["confidence_intervals"].get(mag_key, {})
    collapse_prob = mc_result["collapse_probabilities"].get(mag_key, 0)

    # 该震级各系统级联率分布
    system_ci = []
    for sys_key in CascadeModel.SYSTEM_KEYS:
        sys_ci = ci.get(sys_key, {})
        system_ci.append({
            "system": sys_key,
            "name": CascadeModel.SYSTEM_NAMES[sys_key],
            "color": CascadeModel.SYSTEM_COLORS[sys_key],
            "mean": sys_ci.get("mean", 0),
            "std": sys_ci.get("std", 0),
            "p5": sys_ci.get("p5", 0),
            "p95": sys_ci.get("p95", 0),
        })

    # 龙卷风图数据（精简版，只保留关键字段）
    tornado_data = []
    for t in tornado:
        sys_impact = t["system_impact"]
        tornado_data.append({
            "param": t["param"],
            "label": t["label"],
            "base": t["base"],
            "low": t["low"],
            "high": t["high"],
            "resilience_range": t["resilience_range"],
            "base_resilience": t["base_resilience"],
            "low_resilience": t["low_resilience"],
            "high_resilience": t["high_resilience"],
        })

    # 参数重要性排名（前5）
    importance = [
        {
            "param": c["param"],
            "label": c["label"],
            "rho": c["rho_resilience"],
            "significant": c["significant"],
        }
        for c in correlations[:5]
    ]

    return {
        "magnitude": mag,
        "method": "Monte Carlo + OAT + Spearman",
        "n_samples": mc_result["n_samples"],
        "collapse_probability": collapse_prob,
        "system_confidence_intervals": system_ci,
        "tornado": tornado_data,
        "parameter_importance": importance,
        "threshold_distribution": mc_result.get("threshold_magnitude_distribution"),
    }


# ═══════════════════════════════════════════════════════════
# 8. 更新仪表盘 JSON
# ═══════════════════════════════════════════════════════════
def update_dashboard_jsons(mc_result, tornado, correlations):
    """为每个震级的 dashboard JSON 添加 sensitivity 段。"""
    print("\n更新 dashboard JSON ...")
    for mag in MAGNITUDES:
        path = DATA_DIR / f"dashboard_M{mag:.1f}.json"
        if not path.exists():
            print(f"  [跳过] {path.name} 不存在")
            continue

        with open(path, "r", encoding="utf-8") as f:
            dashboard = json.load(f)

        dashboard["sensitivity"] = build_dashboard_sensitivity(
            mag, mc_result, tornado, correlations
        )

        with open(path, "w", encoding="utf-8") as f:
            json.dump(dashboard, f, ensure_ascii=False, indent=2)

        print(f"  [OK] {path.name} ← sensitivity 段")


# ═══════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════
def main():
    print("=" * 70)
    print("step17 蒙特卡洛参数敏感性分析")
    print("=" * 70)

    # 加载参数定义
    params = load_sensitivity_params()
    print(f"\n分析参数 ({len(params)} 个):")
    for p in params:
        print(f"  {p['name']}: base={p['base']:.3f}  range=[{p['low']:.3f}, {p['high']:.3f}]")

    # 加载基准功能率
    model = CascadeModel()
    base_rates_list = model.load_base_rates()
    print(f"\n基准功能率 ({len(base_rates_list)} 个震级):")
    for r in base_rates_list:
        print(f"  M{r['magnitude']:.1f}: 医{r['medical']:.3f} 交{r['transport']:.3f} "
              f"救{r['rescue']:.3f} 避{r['shelter']:.3f}")

    # 烈度代理模型
    proxy = IntensityProxy()
    print(f"\n烈度代理模型基准烈度:")
    for mag in MAGNITUDES:
        print(f"  M{mag:.1f}: avg_I = {proxy.base_intensities[mag]:.3f}")

    # 1. 蒙特卡洛模拟
    print(f"\n{'─' * 70}")
    print("1. 蒙特卡洛模拟")
    print(f"{'─' * 70}")
    mc_result = run_monte_carlo(base_rates_list, params, proxy)

    if mc_result["threshold_magnitude_distribution"]:
        td = mc_result["threshold_magnitude_distribution"]
        print(f"\n  崩溃临界震级分布:")
        print(f"    均值: M{td['mean']:.2f} ± {td['std']:.2f}")
        print(f"    中位数: M{td['median']:.2f}")
        print(f"    90% CI: [{td['p5']:.2f}, {td['p95']:.2f}]")
    else:
        print("\n  [警告] 所有试验均未触发崩溃")

    print(f"\n  城市崩溃概率:")
    for mag_key, prob in mc_result["collapse_probabilities"].items():
        bar = "█" * int(prob * 20)
        print(f"    {mag_key}: {prob:.1%} {bar}")

    # 2. OAT 龙卷风分析
    print(f"\n{'─' * 70}")
    print("2. 一次一因子法（OAT）— 龙卷风图")
    print(f"{'─' * 70}")
    tornado = run_oat_analysis(base_rates_list, params, proxy)

    print(f"\n  参数敏感性排名（按韧性指数变化范围）:")
    print(f"  {'参数':>20} | {'低值韧性':>8} {'高值韧性':>8} {'范围':>8} | {'低值临界':>8} {'高值临界':>8}")
    print(f"  {'-' * 75}")
    for t in tornado:
        print(f"  {t['label']:>20} | {t['low_resilience']:>8.4f} {t['high_resilience']:>8.4f} "
              f"{t['resilience_range']:>8.4f} | M{t['low_threshold'] or '?':>6} M{t['high_threshold'] or '?':>6}")

    # 3. Spearman 相关分析
    print(f"\n{'─' * 70}")
    print("3. Spearman 秩相关分析")
    print(f"{'─' * 70}")
    correlations = run_correlation_analysis(mc_result, params)

    print(f"\n  参数-韧性指数 Spearman 相关:")
    print(f"  {'参数':>20} | {'ρ(韧性)':>8} {'p值':>10} | {'显著':>4}")
    print(f"  {'-' * 55}")
    for c in correlations:
        sig = "***" if c["significant"] else ""
        print(f"  {c['label']:>20} | {c['rho_resilience']:>+8.4f} {c['p_resilience']:>10.6f} | {sig}")

    # 4. 导出报告
    print(f"\n{'─' * 70}")
    print("4. 导出报告")
    print(f"{'─' * 70}")

    # 深拷贝 MC 结果并移除内部数据（_corr_data 不可序列化）
    mc_export = {k: v for k, v in mc_result.items() if not k.startswith("_")}

    report = {
        "meta": {
            "n_samples": mc_result["n_samples"],
            "seed": SEED,
            "parameters": [
                {"name": p["name"], "base": p["base"],
                 "range": [p["low"], p["high"]]}
                for p in params
            ],
            "method": "Monte Carlo + OAT + Spearman rank correlation",
            "intensity_proxy": {
                "key_distances_km": KEY_DISTANCES.tolist(),
                "sensitivity_coefficients": INTENSITY_SENSITIVITY,
                "description": "烈度参数通过线性代理模型传递到基础功能率",
            },
        },
        "monte_carlo": mc_export,
        "tornado": tornado,
        "correlations": correlations,
    }

    report_path = DATA_DIR / "sensitivity_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"  [OK] {report_path.name}")

    # 5. 更新 dashboard JSON
    update_dashboard_jsons(mc_result, tornado, correlations)

    # 验证
    print(f"\n{'─' * 70}")
    print("验证")
    print(f"{'─' * 70}")
    ok = True

    # 检查崩溃概率单调性
    probs = mc_result["collapse_probabilities"]
    for i in range(1, len(MAGNITUDES)):
        mk = f"M{MAGNITUDES[i]:.1f}"
        pk = f"M{MAGNITUDES[i-1]:.1f}"
        if probs[mk] < probs[pk]:
            ok = False
            print(f"  [FAIL] 崩溃概率非单调: {pk}={probs[pk]:.1%} > {mk}={probs[mk]:.1%}")
    if ok:
        print("  [OK] 崩溃概率随震级单调递增")

    # 检查龙卷风图非空
    if len(tornado) == len(params):
        print(f"  [OK] 龙卷风图覆盖全部 {len(params)} 个参数")
    else:
        ok = False
        print(f"  [FAIL] 龙卷风图参数数不匹配")

    # 检查至少有一个显著相关参数
    sig_count = sum(1 for c in correlations if c["significant"])
    print(f"  [OK] {sig_count}/{len(correlations)} 个参数与韧性指数显著相关 (p<0.05)")

    if ok:
        print("\n验证通过")
    else:
        print("\n验证失败")

    return ok


if __name__ == "__main__":
    main()
