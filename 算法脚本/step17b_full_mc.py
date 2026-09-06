"""
step17b_full_mc.py — 全链路增强蒙特卡洛分析

对 M6.0/M7.0 关键场景各跑 100 次增强蒙特卡洛。

与 step17 的区别（核心升级）：
  step17 使用 7 个关键距离（5~100km）的平均烈度变化作为代理。
  step17b 使用全部 46,758 个网格的真实 yu2013 烈度场重算，
  按人口加权计算平均烈度变化 ΔĪ，更接近真实管线输出。

扰动参数（8 个，同 step17）：
  - 烈度衰减系数 c2, c3（±20% uniform）
  - 跨系统依赖权重 ×4（±20% uniform）
  - 崩溃阈值 ×2（±20% uniform）

代理部分说明：
  烈度变化→基础功能率变化仍使用灵敏度系数线性映射（与 step17 相同）。
  完整管线的 Dijkstra 可达性重算单次需 >30s，100 次不可行。
  但烈度场重算是真实的（46K 网格 yu2013 向量化计算），
  级联模型也是真实的（迭代传播至收敛）。
  因此称为"增强半全链路"而非"纯代理"。

输出：数据文件/full_mc_report.json
"""
import os
import sys
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

# ── GDAL/PROJ 路径 ──
LIB = Path("F:/anaconda/envs/zhenmai/Library/share")
os.environ.setdefault("GDAL_DATA", str(LIB / "gdal"))
os.environ.setdefault("PROJ_LIB", str(LIB / "proj"))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config_loader import get_config
from cascade_model import CascadeModel

# ═══════════════════════════════════════════════════════════
# 全局配置
# ═══════════════════════════════════════════════════════════
cfg = get_config()
DATA_DIR = cfg.data_dir
SEED = 42

# yu2013 参数
yu = cfg.get("intensity", "yu2013", default={})
C1 = yu.get("c1", 1.785)
C2 = yu.get("c2", 1.352)
C3 = yu.get("c3", 1.038)
C4 = yu.get("c4", 0.017)
C5 = yu.get("c5", 0.494)

# 灵敏度系数（与 step17 一致，跨震级数据回归标定）
INTENSITY_SENSITIVITY = {
    "transport": 0.15,
    "medical": 0.10,
    "rescue": 0.10,
    "shelter": 0.08,
}

N_SAMPLES = 100
TARGET_MAGNITUDES = [6.0, 7.0]


# ═══════════════════════════════════════════════════════════
# 1. 数据加载
# ═══════════════════════════════════════════════════════════
def load_grid_data(mag):
    """加载网格烈度+人口数据，按 cell_id 对齐。"""
    intensity_df = pd.read_csv(
        DATA_DIR / f"grid_intensity_M{mag:.1f}.csv", encoding="utf-8-sig")
    pop_df = pd.read_csv(
        DATA_DIR / "grid_population_gdp.csv", encoding="utf-8-sig")
    merged = intensity_df.merge(
        pop_df[["cell_id", "gdp_yi", "dist_to_epi_km", "population"]],
        on="cell_id")
    return merged


def load_base_rates():
    """从 collapse_threshold.csv 加载 6 档基础功能率。"""
    df = pd.read_csv(DATA_DIR / "collapse_threshold.csv", encoding="utf-8-sig")
    rates = {}
    for _, row in df.iterrows():
        mag = float(row["magnitude"])
        rates[mag] = {
            "magnitude": mag,
            "medical": float(row["medical_ratio"]),
            "rescue": float(row["rescue_ratio"]),
            "transport": float(row["transport_ratio"]),
            "shelter": min(float(row["shelter_ratio"]), 1.0),
        }
    return rates


# ═══════════════════════════════════════════════════════════
# 2. yu2013 烈度计算（向量化）
# ═══════════════════════════════════════════════════════════
def yu2013_intensity(c1, c2, c3, c4, c5, M, R):
    """俞言祥 2013 烈度衰减（向量化）。"""
    R = np.maximum(np.asarray(R, dtype=np.float64), 0.1)
    R_sat = R + c4 * np.exp(c5 * M)
    return c1 + c2 * M - c3 * np.log(R_sat)


# ═══════════════════════════════════════════════════════════
# 3. 单次蒙特卡洛试验
# ═══════════════════════════════════════════════════════════
def run_single_trial(mag, grid_data, base_rates, dep_matrix, thresholds,
                     c2_s, c3_s, dep_perturb, thr_perturb):
    """执行一次增强蒙特卡洛试验。

    Args:
        mag: 震级
        grid_data: 网格数据 DataFrame
        base_rates: 该震级的基础功能率 dict
        dep_matrix: 依赖矩阵
        thresholds: 崩溃阈值
        c2_s, c3_s: 采样的烈度系数
        dep_perturb: 依赖权重扰动因子 dict {(target, source): factor}
        thr_perturb: 阈值扰动因子 dict {system: factor}

    Returns:
        dict: 试验结果
    """
    dist_km = grid_data["dist_to_epi_km"].astype(float).values
    population = grid_data["population"].astype(float).values
    pop_weights = population / max(population.sum(), 1.0)

    # 基准烈度（用公式重算，用于计算差分）
    I_base_calc = yu2013_intensity(C1, C2, C3, C4, C5, mag, dist_km)

    # 扰动后烈度（真实 46K 网格重算）
    I_new = yu2013_intensity(C1, c2_s, c3_s, C4, C5, mag, dist_km)

    # 人口加权平均烈度变化
    dI_weighted = float(np.sum(pop_weights * (I_new - I_base_calc)))

    # 调整基础功能率（灵敏度线性映射）
    adjusted_rates = {"magnitude": mag}
    for system in ["medical", "transport", "rescue", "shelter"]:
        base = base_rates[system]
        coef = INTENSITY_SENSITIVITY[system]
        new_rate = base - coef * dI_weighted * (1.0 - base)
        adjusted_rates[system] = max(0.0, min(1.0, new_rate))

    # 构建扰动后的依赖矩阵
    dep_override = {}
    for target in dep_matrix:
        dep_override[target] = dict(dep_matrix[target])
    for (target, source), factor in dep_perturb.items():
        dep_override[target][source] = dep_matrix[target][source] * factor

    # 构建扰动后的阈值
    thr_override = {}
    for key in thresholds:
        thr_override[key] = thresholds[key] * thr_perturb.get(key, 1.0)

    # 创建级联模型并计算
    model = CascadeModel(params_override={
        "dependency_matrix": dep_override,
        "thresholds": thr_override,
    })

    cascade = model.compute_cascade(adjusted_rates, propagation_factor=1.0)
    city_collapse = model.city_collapsed(cascade)

    return {
        "c2": round(c2_s, 4),
        "c3": round(c3_s, 4),
        "dI_weighted": round(dI_weighted, 4),
        "city_collapse": bool(city_collapse),
        "medical_collapse": bool(model.judge_collapse(cascade["medical"], "medical")),
        "rescue_collapse": bool(model.judge_collapse(cascade["rescue"], "rescue")),
        "transport_collapse": bool(model.judge_collapse(cascade["transport"], "transport")),
        "shelter_collapse": bool(model.judge_collapse(cascade["shelter"], "shelter")),
        "cascade_medical": cascade["medical"],
        "cascade_rescue": cascade["rescue"],
        "cascade_transport": cascade["transport"],
        "cascade_shelter": cascade["shelter"],
    }


# ═══════════════════════════════════════════════════════════
# 4. 蒙特卡洛模拟
# ═══════════════════════════════════════════════════════════
def run_mc_for_magnitude(mag, n_samples=N_SAMPLES):
    """对指定震级执行 n_samples 次增强蒙特卡洛。"""
    rng = np.random.default_rng(SEED + int(mag * 10))

    # 加载数据
    grid_data = load_grid_data(mag)
    all_base_rates = load_base_rates()
    base_rates = all_base_rates[mag]

    # 加载依赖矩阵和阈值
    dep_matrix = cfg.get("cascade", "dependency_matrix", default={})
    thresholds = dict(cfg.get("collapse_thresholds", default={}))

    # 收集非零依赖权重
    dep_params = []
    for target in dep_matrix:
        for source in dep_matrix[target]:
            if dep_matrix[target][source] > 0:
                dep_params.append((target, source))

    results = []
    # 参数记录（用于 Spearman 相关分析）
    param_records = {
        "c2": [], "c3": [], "dI": [],
        "dep_factors": [],
        "thr_factors": [],
        "city_collapse": [],
        "medical_ratio": [],
        "rescue_ratio": [],
    }

    for i in range(n_samples):
        # 采样烈度参数
        c2_s = rng.uniform(C2 * 0.8, C2 * 1.2)
        c3_s = rng.uniform(C3 * 0.8, C3 * 1.2)

        # 采样依赖权重扰动因子
        dep_perturb = {}
        for target, source in dep_params:
            dep_perturb[(target, source)] = rng.uniform(0.8, 1.2)

        # 采样阈值扰动因子
        thr_perturb = {}
        for key in thresholds:
            thr_perturb[key] = rng.uniform(0.8, 1.2)

        # 执行试验
        result = run_single_trial(
            mag, grid_data, base_rates, dep_matrix, thresholds,
            c2_s, c3_s, dep_perturb, thr_perturb)

        results.append(result)

        # 记录参数
        param_records["c2"].append(c2_s)
        param_records["c3"].append(c3_s)
        param_records["dI"].append(result["dI_weighted"])
        param_records["dep_factors"].append([dep_perturb[(t, s)] for t, s in dep_params])
        param_records["thr_factors"].append([thr_perturb[k] for k in thresholds])
        param_records["city_collapse"].append(1 if result["city_collapse"] else 0)
        param_records["medical_ratio"].append(result["cascade_medical"])
        param_records["rescue_ratio"].append(result["cascade_rescue"])

        if (i + 1) % 20 == 0:
            print(f"    进度: {i+1}/{n_samples}")

    return results, param_records, dep_params


# ═══════════════════════════════════════════════════════════
# 5. Spearman 秩相关分析
# ═══════════════════════════════════════════════════════════
def spearman_rho(x, y):
    """纯 numpy Spearman 秩相关系数。"""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(x)
    if n < 3:
        return 0.0

    def rank(arr):
        order = np.argsort(arr, kind='mergesort')
        ranks = np.empty(n, dtype=float)
        ranks[order] = np.arange(1, n + 1, dtype=float)
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

    rx, ry = rank(x), rank(y)
    rx_m, ry_m = rx.mean(), ry.mean()
    num = np.sum((rx - rx_m) * (ry - ry_m))
    den = np.sqrt(np.sum((rx - rx_m) ** 2) * np.sum((ry - ry_m) ** 2))
    return float(num / den) if den > 0 else 0.0


def compute_param_importance(param_records, dep_params):
    """计算各参数与医疗级联率的 Spearman 相关。"""
    param_names = ["c2", "c3", "dI"]
    for t, s in dep_params:
        param_names.append(f"dep_{t}←{s}")
    param_names.append("thr_medical")
    param_names.append("thr_rescue")

    # 展开因子列表
    n = len(param_records["c2"])
    all_values = {
        "c2": param_records["c2"],
        "c3": param_records["c3"],
        "dI": param_records["dI"],
    }
    for idx, (t, s) in enumerate(dep_params):
        all_values[f"dep_{t}←{s}"] = [param_records["dep_factors"][i][idx] for i in range(n)]
    thr_keys = list(cfg.get("collapse_thresholds", default={}).keys())
    for idx, key in enumerate(thr_keys):
        all_values[f"thr_{key}"] = [param_records["thr_factors"][i][idx] for i in range(n)]

    target = param_records["medical_ratio"]

    importance = []
    for name in param_names:
        if name in all_values:
            rho = spearman_rho(all_values[name], target)
            importance.append({"param": name, "spearman_rho": round(rho, 4)})

    importance.sort(key=lambda x: abs(x["spearman_rho"]), reverse=True)
    return importance


# ═══════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════
def main():
    print("=" * 70)
    print("step17b 全链路增强蒙特卡洛分析")
    print(f"M{TARGET_MAGNITUDES[0]:.1f}/M{TARGET_MAGNITUDES[1]:.1f} 各 {N_SAMPLES} 次")
    print("真实 46K 网格 yu2013 烈度场重算 + 级联模型真实计算")
    print("=" * 70)

    all_results = {}

    for mag in TARGET_MAGNITUDES:
        print(f"\n{'─' * 60}")
        print(f"■ M{mag:.1f} — {N_SAMPLES} 次蒙特卡洛")
        print(f"{'─' * 60}")

        t0 = time.time()
        results, param_records, dep_params = run_mc_for_magnitude(mag, N_SAMPLES)
        elapsed = time.time() - t0

        # 统计
        n_city = sum(1 for r in results if r["city_collapse"])
        n_med = sum(1 for r in results if r["medical_collapse"])
        n_res = sum(1 for r in results if r["rescue_collapse"])
        n_sh = sum(1 for r in results if r["shelter_collapse"])
        n_tr = sum(1 for r in results if r["transport_collapse"])

        med_ratios = [r["cascade_medical"] for r in results]
        res_ratios = [r["cascade_rescue"] for r in results]
        tr_ratios = [r["cascade_transport"] for r in results]
        sh_ratios = [r["cascade_shelter"] for r in results]

        print(f"\n  耗时: {elapsed:.1f}s ({elapsed/N_SAMPLES:.3f}s/sample)")
        print(f"  城市崩溃: {n_city}/{N_SAMPLES} ({n_city}%)")
        print(f"  医疗崩溃: {n_med}/{N_SAMPLES} ({n_med}%)")
        print(f"  救援崩溃: {n_res}/{N_SAMPLES} ({n_res}%)")
        print(f"  避难崩溃: {n_sh}/{N_SAMPLES} ({n_sh}%)")
        print(f"  交通崩溃: {n_tr}/{N_SAMPLES} ({n_tr}%)")
        print(f"\n  级联功能率统计:")
        for name, ratios in [("医疗", med_ratios), ("救援", res_ratios),
                             ("交通", tr_ratios), ("避难", sh_ratios)]:
            print(f"    {name}: mean={np.mean(ratios):.4f} std={np.std(ratios):.4f} "
                  f"min={np.min(ratios):.4f} max={np.max(ratios):.4f}")

        # 参数重要性
        importance = compute_param_importance(param_records, dep_params)
        print(f"\n  参数重要性 (Spearman ρ vs 医疗级联率):")
        for imp in importance[:5]:
            print(f"    {imp['param']:>25}: {imp['spearman_rho']:+.4f}")

        all_results[f"M{mag:.1f}"] = {
            "n_samples": N_SAMPLES,
            "elapsed_sec": round(elapsed, 1),
            "city_collapse_count": n_city,
            "city_collapse_pct": n_city,
            "system_collapse": {
                "medical": n_med,
                "rescue": n_res,
                "shelter": n_sh,
                "transport": n_tr,
            },
            "cascade_stats": {
                "medical": {
                    "mean": round(float(np.mean(med_ratios)), 4),
                    "std": round(float(np.std(med_ratios)), 4),
                    "min": round(float(np.min(med_ratios)), 4),
                    "max": round(float(np.max(med_ratios)), 4),
                    "p5": round(float(np.percentile(med_ratios, 5)), 4),
                    "p95": round(float(np.percentile(med_ratios, 95)), 4),
                },
                "rescue": {
                    "mean": round(float(np.mean(res_ratios)), 4),
                    "std": round(float(np.std(res_ratios)), 4),
                    "min": round(float(np.min(res_ratios)), 4),
                    "max": round(float(np.max(res_ratios)), 4),
                    "p5": round(float(np.percentile(res_ratios, 5)), 4),
                    "p95": round(float(np.percentile(res_ratios, 95)), 4),
                },
                "transport": {
                    "mean": round(float(np.mean(tr_ratios)), 4),
                    "std": round(float(np.std(tr_ratios)), 4),
                },
                "shelter": {
                    "mean": round(float(np.mean(sh_ratios)), 4),
                    "std": round(float(np.std(sh_ratios)), 4),
                },
            },
            "param_importance": importance,
        }

    # 总结
    print(f"\n{'=' * 70}")
    print("总结")
    print(f"{'=' * 70}")
    for mag_key, r in all_results.items():
        print(f"  {mag_key}: 城市崩溃 {r['city_collapse_pct']}% | "
              f"医疗 {r['system_collapse']['medical']}% | "
              f"救援 {r['system_collapse']['rescue']}% | "
              f"避难 {r['system_collapse']['shelter']}%")

    # 保存报告
    report = {
        "title": "全链路增强蒙特卡洛分析",
        "method": "enhanced_semi_full",
        "method_description": (
            "对 M6.0/M7.0 各 100 次: 真实 46K 网格 yu2013 烈度场重算 → "
            "人口加权 ΔI → 灵敏度线性映射 → 8 参数联合扰动 → "
            "级联模型迭代传播真实计算"
        ),
        "comparison_with_step17": {
            "step17_proxy": "7 关键距离平均烈度 → 线性映射 (纯代理)",
            "step17b_enhanced": "46K 网格真实烈度场重算 → 人口加权 ΔI → 线性映射 (增强半全链路)",
            "improvement": "烈度变化估计从 7 点平均升级为 46K 网格人口加权，更接近真实管线输出",
            "remaining_proxy": "烈度→功能率映射仍为线性灵敏度系数（Dijkstra 可达性重算单次 >30s 不可行）",
        },
        "results": all_results,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    output_path = DATA_DIR / "full_mc_report.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n报告已保存: {output_path}")


if __name__ == "__main__":
    main()
