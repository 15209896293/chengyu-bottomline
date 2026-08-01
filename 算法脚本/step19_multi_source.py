"""
step19_multi_source.py — 多震源情景对比模块

对 config.yaml 中 multi_source.scenarios 定义的 4 个潜在震源情景，
分别计算其在合肥市域（以 config epicenter 为中心约 50km 范围）产生的
烈度场、破裂带参数、级联传播影响，并输出对比结果与等值线数据。

依赖：
  - intensity_model.py  （俞言祥 2013 烈度衰减）
  - rupture_model.py    （Wells & Coppersmith 1994 破裂参数）
  - cascade_model.py    （迭代传播级联模型）
  - config_loader.py    （config.yaml 配置读取）

输出：
  数据文件/multi_source_comparison.json
"""
import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np

from config_loader import get_config
from intensity_model import IntensityModel
from rupture_model import RuptureModel
from cascade_model import CascadeModel


# ═══════════════════════════════════════════════════════════
# 地理工具
# ═══════════════════════════════════════════════════════════
EARTH_RADIUS_KM = 6371.0088  # 地球平均半径(km)


def haversine(lon1, lat1, lon2, lat2):
    """haversine 球面距离公式，返回两点间大圆距离(km)。"""
    lon1, lat1, lon2, lat2 = map(math.radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = (math.sin(dlat / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    return EARTH_RADIUS_KM * 2 * math.asin(math.sqrt(a))


def haversine_grid(epi_lon, epi_lat, grid_lon, grid_lat):
    """向量化 haversine：震中(标量)到网格(数组)的距离场(km)。"""
    epi_lon_r = math.radians(epi_lon)
    epi_lat_r = math.radians(epi_lat)
    dlon = np.radians(grid_lon) - epi_lon_r
    dlat = np.radians(grid_lat) - epi_lat_r
    a = (np.sin(dlat / 2) ** 2
         + math.cos(epi_lat_r) * np.cos(np.radians(grid_lat))
         * np.sin(dlon / 2) ** 2)
    return EARTH_RADIUS_KM * 2 * np.arcsin(np.sqrt(a))


def build_city_grid(center_lon, center_lat, radius_km=50, step_km=2.0):
    """以中心点为中心构建方形经纬度网格。

    Args:
        center_lon, center_lat: 中心经纬度
        radius_km: 半边长(km)
        step_km: 网格间距(km)

    Returns:
        lons, lats: 一维坐标数组
        grid_lon, grid_lat: 二维网格坐标(meshgrid, shape=[rows, cols])
    """
    # 1° 纬度 ≈ 111.32 km；1° 经度 ≈ 111.32 * cos(lat) km
    deg_per_km_lat = 1.0 / 111.32
    deg_per_km_lon = 1.0 / (111.32 * math.cos(math.radians(center_lat)))
    half_lat = radius_km * deg_per_km_lat
    half_lon = radius_km * deg_per_km_lon
    n = int(radius_km / step_km) * 2 + 1
    lats = np.linspace(center_lat - half_lat, center_lat + half_lat, n)
    lons = np.linspace(center_lon - half_lon, center_lon + half_lon, n)
    grid_lon, grid_lat = np.meshgrid(lons, lats)
    return lons, lats, grid_lon, grid_lat


# ═══════════════════════════════════════════════════════════
# 烈度场与等值线
# ═══════════════════════════════════════════════════════════
# MMI 等级分界（与 intensity_to_grade 的边界一致）
CONTOUR_LEVELS = [4.5, 5.5, 6.5, 7.5, 8.5, 9.5, 10.5, 11.5]


def compute_intensity_field(imodel, epicenter, magnitude, grid_lon, grid_lat):
    """计算震源在网格各点的烈度场(MMI)。

    Args:
        imodel: IntensityModel 实例
        epicenter: (lon, lat) 震中
        magnitude: 震级
        grid_lon, grid_lat: 二维网格坐标

    Returns:
        intensities: 二维烈度数组, shape 与网格一致
    """
    epi_lon, epi_lat = epicenter
    distances = haversine_grid(epi_lon, epi_lat, grid_lon, grid_lat)
    # 用 compute_field 按距离批量计算，再还原为网格形状
    flat_int = imodel.compute_field(magnitude, distances.flatten())
    return flat_int.reshape(distances.shape)


def compute_grade_distribution(imodel, intensities):
    """统计各烈度等级在网格中的面积占比。"""
    total = intensities.size
    counts = {}
    for v in intensities.flatten():
        g = imodel.intensity_to_grade(float(v))
        counts[g] = counts.get(g, 0) + 1
    return {g: round(c / total, 4) for g, c in sorted(counts.items())}


def _level_to_grade(level):
    """等值线级别 → 相邻烈度等级标签。"""
    mapping = {4.5: "IV-V", 5.5: "V-VI", 6.5: "VI-VII", 7.5: "VII-VIII",
               8.5: "VIII-IX", 9.5: "IX-X", 10.5: "X-XI", 11.5: "XI-XII"}
    return mapping.get(level, str(level))


def extract_iso_lines(lons, lats, intensities, levels=CONTOUR_LEVELS):
    """从烈度网格提取等值线多段线(前端可视化用)。

    依赖 matplotlib 的 contour；若不可用则返回空列表，
    前端可退化为直接用 grid 数据自行渲染。
    """
    try:
        import matplotlib
        matplotlib.use("Agg")  # 无界面后端，避免弹窗
        import matplotlib.pyplot as plt
    except ImportError:
        return []

    fig, ax = plt.subplots()
    cs = ax.contour(lons, lats, intensities, levels=levels)
    iso_lines = []
    for level, segs in zip(cs.levels, cs.allsegs):
        paths = []
        for seg in segs:
            if len(seg) == 0:
                continue
            paths.append([[float(x), float(y)] for x, y in seg])
        iso_lines.append({
            "level": float(level),
            "grade": _level_to_grade(level),
            "paths": paths,
        })
    plt.close(fig)
    return iso_lines


# ═══════════════════════════════════════════════════════════
# 级联分析：平均烈度 → 基础功能率
# ═══════════════════════════════════════════════════════════
def intensity_to_base_rates(avg_intensity):
    """平均烈度 → 四系统基础功能率。

    基础映射: rate = 1 - I/12
        （烈度 XII 时功能率归零，I=0 时满功能）
    系统差异化系数(体现各系统对地面震动的敏感度)：
      - 交通 transport: 路网直接受震动破坏，敏感度最高 → ×1.15
      - 救援 rescue:    依赖交通出勤，略高 → ×1.05
      - 医疗 medical:   抗震设防，基准 → ×1.00
      - 避难 shelter:   间接受建筑倒塌影响，略低 → ×0.90
    """
    def _rate(coef):
        return round(max(0.0, min(1.0, 1.0 - avg_intensity * coef / 12.0)), 4)

    return {
        "medical": _rate(1.00),
        "transport": _rate(1.15),
        "rescue": _rate(1.05),
        "shelter": _rate(0.90),
    }


# ═══════════════════════════════════════════════════════════
# 单情景分析
# ═══════════════════════════════════════════════════════════
def analyze_scenario(scenario, imodel, rmodel, cmodel, hefei_center,
                     grid_lon, grid_lat, lons, lats):
    """分析单个震源情景，返回该情景的完整结果字典。"""
    name = scenario["name"]
    epi = tuple(scenario["epicenter"])  # (lon, lat)
    mag = float(scenario["mag"])
    fault = scenario.get("fault", "")

    # 1. 震源到合肥市中心的球面距离
    dist_to_hefei = haversine(epi[0], epi[1], hefei_center[0], hefei_center[1])

    # 2. 破裂带参数（Wells & Coppersmith 1994）
    rupture = rmodel.full_parameters(mag)

    # 3. 烈度场统计
    intensities = compute_intensity_field(imodel, epi, mag, grid_lon, grid_lat)
    avg_intensity = round(float(np.mean(intensities)), 3)
    max_intensity = round(float(np.max(intensities)), 3)
    min_intensity = round(float(np.min(intensities)), 3)
    # 市中心烈度（距离震中 dist_to_hefei，近场保护下限 0.1km）
    intensity_at_hefei = round(
        float(imodel.compute(mag, max(dist_to_hefei, 0.1))), 3)
    grade_dist = compute_grade_distribution(imodel, intensities)

    # 4. 级联传播分析（用平均烈度推算基础功能率）
    base_rates = intensity_to_base_rates(avg_intensity)
    cascade = cmodel.compute_cascade(base_rates, propagation_factor=1.0)
    system_status = {
        k: cmodel.system_status(cascade[k], k) for k in cmodel.SYSTEM_KEYS
    }
    collapses = {
        k: cmodel.judge_collapse(cascade[k], k) for k in cmodel.SYSTEM_KEYS
    }

    # 5. 烈度等值线（前端可视化）
    iso_lines = extract_iso_lines(lons, lats, intensities)

    return {
        "name": name,
        "epicenter": [round(epi[0], 4), round(epi[1], 4)],
        "fault": fault,
        "magnitude": mag,
        "distance_to_hefei_km": round(dist_to_hefei, 2),
        "rupture": {
            "width_km": rupture["width_km"],
            "width_m": rupture["width_m"],
            "length_km": rupture["length_km"],
            "displacement_m": rupture["displacement_m"],
            "fault_type": rupture["fault_type"],
            "reference": rupture["reference"],
        },
        "intensity_field": {
            "avg_intensity": avg_intensity,
            "max_intensity": max_intensity,
            "min_intensity": min_intensity,
            "intensity_at_hefei": intensity_at_hefei,
            "max_grade": imodel.intensity_to_grade(max_intensity),
            "grade_distribution": grade_dist,
        },
        "cascade": {
            "base_rates": base_rates,
            "cascade_rates": {
                "medical": cascade["medical"],
                "transport": cascade["transport"],
                "rescue": cascade["rescue"],
                "shelter": cascade["shelter"],
            },
            "drops": {
                "medical": cascade["medical_drop"],
                "transport": cascade["transport_drop"],
                "rescue": cascade["rescue_drop"],
                "shelter": cascade["shelter_drop"],
            },
            "collapses": collapses,
            "city_collapsed": cmodel.city_collapsed(cascade),
            "system_status": system_status,
        },
        "contour_data": {
            "bounds": {
                "min_lon": round(float(lons[0]), 4),
                "max_lon": round(float(lons[-1]), 4),
                "min_lat": round(float(lats[0]), 4),
                "max_lat": round(float(lats[-1]), 4),
            },
            "rows": int(len(lats)),
            "cols": int(len(lons)),
            "lons": [round(float(x), 4) for x in lons],
            "lats": [round(float(x), 4) for x in lats],
            "intensities": [[round(float(v), 3) for v in row]
                            for row in intensities],
            "iso_lines": iso_lines,
        },
    }


# ═══════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════
def run_multi_source_analysis():
    """执行多震源情景对比分析，返回完整结果字典。"""
    cfg = get_config()

    hefei_center = tuple(cfg.epicenter)  # (117.28, 31.82)
    scenarios = cfg.get("multi_source", "scenarios", default=[])

    imodel = IntensityModel()       # 默认 yu2013
    rmodel = RuptureModel()
    cmodel = CascadeModel()

    # 构建合肥市域网格（中心 ±50km，2km 步长）
    radius_km = 50
    step_km = 2.0
    lons, lats, grid_lon, grid_lat = build_city_grid(
        hefei_center[0], hefei_center[1],
        radius_km=radius_km, step_km=step_km)

    # 逐情景分析
    scenario_results = [
        analyze_scenario(s, imodel, rmodel, cmodel, hefei_center,
                         grid_lon, grid_lat, lons, lats)
        for s in scenarios
    ]

    # 对比汇总
    by_intensity = sorted(
        scenario_results,
        key=lambda x: x["intensity_field"]["avg_intensity"],
        reverse=True)
    by_collapse = sorted(
        scenario_results,
        key=lambda x: sum(x["cascade"]["collapses"].values()),
        reverse=True)

    comparison = {
        "ranking_by_avg_intensity": [
            {"name": s["name"],
             "avg_intensity": s["intensity_field"]["avg_intensity"],
             "distance_km": s["distance_to_hefei_km"]}
            for s in by_intensity
        ],
        "ranking_by_collapse_risk": [
            {"name": s["name"],
             "collapsed_count": sum(s["cascade"]["collapses"].values()),
             "city_collapsed": s["cascade"]["city_collapsed"]}
            for s in by_collapse
        ],
        "rupture_width_comparison": [
            {"name": s["name"], "magnitude": s["magnitude"],
             "width_km": s["rupture"]["width_km"],
             "length_km": s["rupture"]["length_km"]}
            for s in scenario_results
        ],
    }

    return {
        "meta": {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "hefei_center": [hefei_center[0], hefei_center[1]],
            "grid_radius_km": radius_km,
            "grid_step_km": step_km,
            "grid_size": [int(len(lats)), int(len(lons))],
            "intensity_model": imodel.info(),
            "rupture_model": {
                "model": rmodel.model_name,
                "fault_type": rmodel.fault_type,
                "reference": rmodel.full_parameters(6.0)["reference"],
            },
            "scenario_count": len(scenario_results),
        },
        "scenarios": scenario_results,
        "comparison": comparison,
    }


def save_result(result, path=None):
    """保存结果到 JSON 文件。"""
    if path is None:
        cfg = get_config()
        path = cfg.data_dir / "multi_source_comparison.json"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return path


# ═══════════════════════════════════════════════════════════
# 自测验证
# ═══════════════════════════════════════════════════════════
def self_test(result):
    """对分析结果做合理性校验。"""
    scenarios = result["scenarios"]
    assert len(scenarios) == 4, f"应有 4 个情景，实际 {len(scenarios)}"

    by_name = {s["name"]: s for s in scenarios}
    hefei = by_name["郯庐带合肥段"]
    feidong = by_name["肥东断裂"]
    dabie = by_name["大别山断裂"]
    suqian = by_name["宿迁段迁移"]

    # 1. 距离合理性：合肥段震中即市中心，距离应≈0 且最近
    assert hefei["distance_to_hefei_km"] < 1.0, "合肥段应最近(距市中心≈0)"
    assert hefei["distance_to_hefei_km"] <= feidong["distance_to_hefei_km"], \
        "合肥段距离应 <= 肥东"

    # 2. 距离排序：合肥段最小
    dists = [s["distance_to_hefei_km"] for s in scenarios]
    assert min(dists) == hefei["distance_to_hefei_km"], "合肥段距离应最小"
    # 宿迁段最远(距合肥约 250km)
    assert max(dists) == suqian["distance_to_hefei_km"], "宿迁段距离应最大"

    # 3. 烈度合理性：合肥段(最近+M6.5)平均烈度最高
    avg_ints = {s["name"]: s["intensity_field"]["avg_intensity"]
                for s in scenarios}
    assert max(avg_ints.values()) == avg_ints["郯庐带合肥段"], \
        "合肥段平均烈度应最高"

    # 4. 大别山对合肥烈度影响最小(距离远+M6.0 → 平均烈度最低)
    assert avg_ints["大别山断裂"] == min(avg_ints.values()), \
        "大别山断裂对合肥烈度影响应最小"

    # 5. 烈度范围合理
    for s in scenarios:
        ai = s["intensity_field"]["avg_intensity"]
        assert 3.0 <= ai <= 12.0, f"{s['name']} 平均烈度 {ai} 越界"

    # 6. 破裂宽度随震级递增
    assert hefei["rupture"]["width_km"] > feidong["rupture"]["width_km"], \
        "M6.5 破裂宽度应 > M6.0"
    assert suqian["rupture"]["width_km"] > hefei["rupture"]["width_km"], \
        "M7.0 破裂宽度应 > M6.5"

    # 7. 级联功能率 <= 基础功能率（级联只会降低功能率）
    for s in scenarios:
        c = s["cascade"]
        for k in ["medical", "rescue", "shelter"]:
            assert c["cascade_rates"][k] <= c["base_rates"][k] + 1e-6, \
                f"{s['name']} {k} 级联率应 <= 基础率"

    print("[OK] 自测全部通过")
    return True


def main():
    print("=" * 70)
    print("多震源情景对比分析")
    print("=" * 70)

    result = run_multi_source_analysis()

    # 摘要输出
    meta = result["meta"]
    print(f"\n合肥市中心: {meta['hefei_center']}")
    print(f"分析网格: {meta['grid_size']} (±{meta['grid_radius_km']}km, "
          f"步长 {meta['grid_step_km']}km)")
    print(f"烈度模型: {meta['intensity_model']['model']}")
    print(f"情景数量: {meta['scenario_count']}")

    print(f"\n{'情景':<14} {'震级':>5} {'距合肥km':>9} {'平均烈度':>8} "
          f"{'市中心烈度':>10} {'破裂宽km':>9} {'城市崩溃':>8}")
    print("-" * 80)
    for s in result["scenarios"]:
        print(f"{s['name']:<14} M{s['magnitude']:<4.1f} "
              f"{s['distance_to_hefei_km']:>8.1f} "
              f"{s['intensity_field']['avg_intensity']:>8.3f} "
              f"{s['intensity_field']['intensity_at_hefei']:>10.3f} "
              f"{s['rupture']['width_km']:>9.4f} "
              f"{'是' if s['cascade']['city_collapsed'] else '否':>8}")

    # 排序结果
    print("\n距离排序(近→远):",
          " < ".join(s["name"] for s in sorted(
              result["scenarios"], key=lambda x: x["distance_to_hefei_km"])))
    print("平均烈度排序(高→低):",
          " > ".join(s["name"] for s in sorted(
              result["scenarios"],
              key=lambda x: x["intensity_field"]["avg_intensity"],
              reverse=True)))

    # 自测
    print()
    self_test(result)

    # 保存
    path = save_result(result)
    print(f"\n结果已保存: {path}")
    return result


if __name__ == "__main__":
    main()
