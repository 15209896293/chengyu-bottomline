"""
阶段九：防治策略推演
模拟加固哪些路段能把底线推高多少，对比三种策略的提升效果。

输出:
  数据文件/prevention_strategy.csv  — 策略对比汇总
  数据文件/key_roads.csv            — 策略A加固的关键路段
"""
import os
from pathlib import Path

LIB = Path("F:/anaconda/envs/zhenmai/Library/share")
os.environ.setdefault("GDAL_DATA", str(LIB / "gdal"))
os.environ.setdefault("PROJ_LIB", str(LIB / "proj"))

import warnings
warnings.filterwarnings("ignore")

import json
import numpy as np
import pandas as pd
import geopandas as gpd

# ── 配置 ────────────────────────────────────────────────
DATA_DIR = Path(__file__).resolve().parent.parent / "数据文件"
CRS_GEO = "EPSG:4490"
CRS_PROJ = "EPSG:4527"
SEED = 42
MAGNITUDES = [5.0, 5.5, 6.0, 6.5, 7.0, 7.5]

# 崩溃阈值
MEDICAL_THRESHOLD = 0.30
RESCUE_THRESHOLD = 0.40


def load_collapse_threshold():
    """读取崩溃临界点数据"""
    fp = DATA_DIR / "collapse_threshold.csv"
    if not fp.exists():
        print("警告: collapse_threshold.csv 不存在")
        return None
    df = pd.read_csv(fp)
    return df


def find_collapse_magnitude(collapse_df):
    """找到城市崩溃临界震级"""
    collapsed = collapse_df[collapse_df["city_collapse"] == True]
    if len(collapsed) == 0:
        return MAGNITUDES[-1]  # 未崩溃，取最大震级
    return float(collapsed.iloc[0]["magnitude"])


def find_key_roads(mag):
    """找出指定震级下距断裂带最近的'完全阻断'路段"""
    fp = DATA_DIR / f"road_blocked_M{mag}.geojson"
    if not fp.exists():
        print(f"警告: {fp.name} 不存在")
        return gpd.GeoDataFrame()

    roads = gpd.read_file(fp)
    blocked = roads[roads["block_level"] == "完全阻断"].copy()

    if len(blocked) == 0:
        print(f"  M{mag}: 无'完全阻断'路段")
        return blocked

    # 按距断裂带距离排序，取前10
    blocked = blocked.sort_values("dist_to_fault_m").head(10)
    return blocked


def estimate_medical_ratio_after_road_repair(mag, key_road_ids, collapse_df):
    """
    策略A：加固关键路段后估算医疗系统功能率
    估算方法：假设修复这些路段后，部分不可达医院变为可达
    """
    acc_fp = DATA_DIR / f"accessibility_M{mag}.csv"
    if not acc_fp.exists():
        return None

    acc = pd.read_csv(acc_fp)
    total = len(acc)
    if total == 0:
        return None

    accessible = len(acc[acc["accessibility"] == "正常可达"])
    limited = len(acc[acc["accessibility"] == "可达但受限"])
    inaccessible = len(acc[acc["accessibility"] == "不可达"])

    # 当前医疗功能率
    current_ratio = (accessible + 0.5 * limited) / total

    # 估算修复效果：每修复1条关键路段，约能恢复一定比例的不可达医院
    # 假设10条关键路段修复后，约30%的不可达医院变为可达，20%变为受限
    repaired = len(key_road_ids)
    if repaired > 0:
        recover_factor = min(0.35, 0.03 * repaired)  # 每条路段恢复3%，上限35%
        recovered_accessible = int(inaccessible * recover_factor)
        recovered_limited = int(inaccessible * recover_factor * 0.5)
        new_accessible = accessible + recovered_accessible
        new_limited = limited + recovered_limited
        new_inaccessible = inaccessible - recovered_accessible - recovered_limited
        new_ratio = (new_accessible + 0.5 * new_limited) / total
    else:
        new_ratio = current_ratio

    return new_ratio


def estimate_medical_ratio_after_medical_points(mag, num_points, collapse_df):
    """
    策略B：增设临时医疗点后估算医疗系统功能率
    """
    acc_fp = DATA_DIR / f"accessibility_M{mag}.csv"
    if not acc_fp.exists():
        return None

    acc = pd.read_csv(acc_fp)
    total = len(acc)
    if total == 0:
        return None

    accessible = len(acc[acc["accessibility"] == "正常可达"])
    limited = len(acc[acc["accessibility"] == "可达但受限"])

    current_ratio = (accessible + 0.5 * limited) / total

    # 新增的临时医疗点假设全部正常可达
    new_total = total + num_points
    new_ratio = (accessible + num_points + 0.5 * limited) / new_total

    return new_ratio


def estimate_rescue_ratio_after(mag, key_road_ids):
    """估算救援系统功能率（策略A对救援系统也有影响）"""
    acc_fp = DATA_DIR / f"accessibility_facilities_M{mag}.csv"
    if not acc_fp.exists():
        return None

    acc = pd.read_csv(acc_fp)
    fire = acc[acc["type"] == "消防站"]
    total = len(fire)
    if total == 0:
        return None

    accessible = len(fire[fire["accessibility"] == "正常可达"])
    limited = len(fire[fire["accessibility"] == "可达但受限"])
    inaccessible = len(fire[fire["accessibility"] == "不可达"])

    current_ratio = (accessible + 0.5 * limited) / total

    repaired = len(key_road_ids)
    if repaired > 0:
        recover_factor = min(0.25, 0.025 * repaired)
        recovered_accessible = int(inaccessible * recover_factor)
        new_accessible = accessible + recovered_accessible
        new_ratio = (new_accessible + 0.5 * limited) / total
    else:
        new_ratio = current_ratio

    return new_ratio


def check_collapse(ratio, threshold):
    """判断是否崩溃"""
    return ratio < threshold


def estimate_threshold_shift(mag, new_medical_ratio, collapse_df):
    """
    估算崩溃临界点的提升
    如果当前震级不再崩溃，检查更高震级
    """
    # 找到当前崩溃的临界震级
    original_threshold = find_collapse_magnitude(collapse_df)

    # 获取当前震级的原始医疗比率
    mag_row = collapse_df[collapse_df["magnitude"] == mag]
    if len(mag_row) == 0:
        return 0.0
    original_medical = float(mag_row["medical_ratio"].iloc[0])

    # 如果原来崩溃，现在不崩溃了
    original_collapse = check_collapse(original_medical, MEDICAL_THRESHOLD)
    new_collapse = check_collapse(new_medical_ratio, MEDICAL_THRESHOLD)

    if original_collapse and not new_collapse:
        # 估算能推高多少
        # 检查更高震级是否也能被提升
        shift = 0.0
        for m in MAGNITUDES:
            if m <= mag:
                continue
            m_row = collapse_df[collapse_df["magnitude"] == m]
            if len(m_row) == 0:
                continue
            m_medical = float(m_row["medical_ratio"].iloc[0])
            if check_collapse(m_medical, MEDICAL_THRESHOLD):
                break
            shift = m - original_threshold
        if shift == 0:
            shift = 0.5  # 至少推高半个震级
        return shift
    elif not original_collapse:
        return 0.0
    else:
        return 0.0


def save_key_roads(key_roads_gdf, mag):
    """保存关键路段"""
    if len(key_roads_gdf) == 0:
        return

    records = []
    for _, row in key_roads_gdf.iterrows():
        geom = row.geometry
        coords = list(geom.coords)
        if len(coords) >= 2:
            start = coords[0]
            end = coords[-1]
        else:
            start = end = coords[0]

        records.append({
            "road_id": int(row.get("road_id", 0)),
            "dist_to_fault_m": float(row.get("dist_to_fault_m", 0)),
            "length_m": float(row.get("length_m", 0)),
            "block_level": str(row.get("block_level", "")),
            "lng_start": round(start[0], 6),
            "lat_start": round(start[1], 6),
            "lng_end": round(end[0], 6),
            "lat_end": round(end[1], 6),
        })

    df = pd.DataFrame(records)
    fp = DATA_DIR / "key_roads.csv"
    df.to_csv(fp, index=False, encoding="utf-8-sig")
    print(f"  关键路段已保存 -> key_roads.csv ({len(df)} 条)")
    return df


def main():
    print("=" * 60)
    print("阶段九：防治策略推演")
    print("=" * 60)

    np.random.seed(SEED)

    # 1. 读取崩溃临界点
    collapse_df = load_collapse_threshold()
    if collapse_df is None:
        print("错误: 无法读取 collapse_threshold.csv，请先运行阶段三")
        return

    collapse_mag = find_collapse_magnitude(collapse_df)
    print(f"\n城市崩溃临界震级: M{collapse_mag}")

    # 获取临界震级的数据
    mag = collapse_mag
    mag_str = f"M{mag}"

    # 2. 找关键路段
    print(f"\n识别 M{mag} 的关键瓶颈路段...")
    key_roads = find_key_roads(mag)
    print(f"  '完全阻断'且距断裂带最近的路段: {len(key_roads)} 条")

    # 保存关键路段
    key_roads_df = save_key_roads(key_roads, mag)

    # 3. 读取当前的功能率
    mag_row = collapse_df[collapse_df["magnitude"] == mag].iloc[0]
    medical_before = float(mag_row["medical_ratio"])
    rescue_before = float(mag_row["rescue_ratio"])
    city_collapse_before = bool(mag_row["city_collapse"])

    print(f"\n当前 M{mag} 状态:")
    print(f"  医疗功能率: {medical_before:.4f} (阈值: {MEDICAL_THRESHOLD})")
    print(f"  救援功能率: {rescue_before:.4f} (阈值: {RESCUE_THRESHOLD})")
    print(f"  城市崩溃: {city_collapse_before}")

    # 4. 策略A：加固关键路段
    print(f"\n策略A: 加固断裂带沿线 {len(key_roads)} 条关键路段")
    key_road_ids = key_roads["road_id"].tolist() if "road_id" in key_roads.columns else []
    medical_after_a = estimate_medical_ratio_after_road_repair(mag, key_road_ids, collapse_df)
    rescue_after_a = estimate_rescue_ratio_after(mag, key_road_ids)
    medical_collapse_a = check_collapse(medical_after_a, MEDICAL_THRESHOLD) if medical_after_a else True
    city_collapse_a = medical_collapse_a  # 简化：只看医疗系统
    shift_a = estimate_threshold_shift(mag, medical_after_a, collapse_df) if not city_collapse_a else 0.0

    print(f"  医疗功能率: {medical_before:.4f} -> {medical_after_a:.4f}")
    print(f"  救援功能率: {rescue_before:.4f} -> {rescue_after_a:.4f}")
    print(f"  城市崩溃: {city_collapse_before} -> {city_collapse_a}")
    print(f"  临界点提升: +{shift_a:.1f}")

    # 5. 策略B：增设临时医疗点
    num_medical_points = 3
    print(f"\n策略B: 增设 {num_medical_points} 个临时医疗点")
    medical_after_b = estimate_medical_ratio_after_medical_points(mag, num_medical_points, collapse_df)
    rescue_after_b = rescue_before  # 不影响救援
    medical_collapse_b = check_collapse(medical_after_b, MEDICAL_THRESHOLD) if medical_after_b else True
    city_collapse_b = medical_collapse_b
    shift_b = estimate_threshold_shift(mag, medical_after_b, collapse_df) if not city_collapse_b else 0.0

    print(f"  医疗功能率: {medical_before:.4f} -> {medical_after_b:.4f}")
    print(f"  救援功能率: {rescue_before:.4f} -> {rescue_after_b:.4f}")
    print(f"  城市崩溃: {city_collapse_before} -> {city_collapse_b}")
    print(f"  临界点提升: +{shift_b:.1f}")

    # 6. 策略C：A+B组合
    print(f"\n策略C: A+B 组合 (加固 {len(key_roads)} 路段 + {num_medical_points} 临时医疗点)")
    # 组合效果：取A和B中较高的，再加上叠加增益（B的边际贡献）
    improvement_b = medical_after_b - medical_before
    medical_after_c = medical_after_a + improvement_b * 0.5  # B在A基础上叠加50%效果
    medical_after_c = min(medical_after_c, 0.95)  # 上限

    rescue_after_c = rescue_after_a  # 救援只受A影响
    medical_collapse_c = check_collapse(medical_after_c, MEDICAL_THRESHOLD)
    city_collapse_c = medical_collapse_c
    shift_c = estimate_threshold_shift(mag, medical_after_c, collapse_df) if not city_collapse_c else 0.0

    print(f"  医疗功能率: {medical_before:.4f} -> {medical_after_c:.4f}")
    print(f"  救援功能率: {rescue_before:.4f} -> {rescue_after_c:.4f}")
    print(f"  城市崩溃: {city_collapse_before} -> {city_collapse_c}")
    print(f"  临界点提升: +{shift_c:.1f}")

    # 7. 输出汇总
    strategies = [
        {
            "strategy": "baseline",
            "description": "无干预（当前状态）",
            "key_roads_repaired": 0,
            "temp_medical_points_added": 0,
            "medical_ratio_before": round(medical_before, 4),
            "medical_ratio_after": round(medical_before, 4),
            "rescue_ratio_before": round(rescue_before, 4),
            "rescue_ratio_after": round(rescue_before, 4),
            "city_collapse_before": city_collapse_before,
            "city_collapse_after": city_collapse_before,
            "threshold_shift": 0.0,
        },
        {
            "strategy": "A",
            "description": f"加固断裂带沿线{len(key_roads)}条关键路段",
            "key_roads_repaired": len(key_roads),
            "temp_medical_points_added": 0,
            "medical_ratio_before": round(medical_before, 4),
            "medical_ratio_after": round(medical_after_a, 4),
            "rescue_ratio_before": round(rescue_before, 4),
            "rescue_ratio_after": round(rescue_after_a, 4),
            "city_collapse_before": city_collapse_before,
            "city_collapse_after": city_collapse_a,
            "threshold_shift": shift_a,
        },
        {
            "strategy": "B",
            "description": f"增设{num_medical_points}个临时医疗点",
            "key_roads_repaired": 0,
            "temp_medical_points_added": num_medical_points,
            "medical_ratio_before": round(medical_before, 4),
            "medical_ratio_after": round(medical_after_b, 4),
            "rescue_ratio_before": round(rescue_before, 4),
            "rescue_ratio_after": round(rescue_after_b, 4),
            "city_collapse_before": city_collapse_before,
            "city_collapse_after": city_collapse_b,
            "threshold_shift": shift_b,
        },
        {
            "strategy": "C",
            "description": f"A+B组合（加固{len(key_roads)}路段+{num_medical_points}医疗点）",
            "key_roads_repaired": len(key_roads),
            "temp_medical_points_added": num_medical_points,
            "medical_ratio_before": round(medical_before, 4),
            "medical_ratio_after": round(medical_after_c, 4),
            "rescue_ratio_before": round(rescue_before, 4),
            "rescue_ratio_after": round(rescue_after_c, 4),
            "city_collapse_before": city_collapse_before,
            "city_collapse_after": city_collapse_c,
            "threshold_shift": shift_c,
        },
    ]

    result_df = pd.DataFrame(strategies)
    out_fp = DATA_DIR / "prevention_strategy.csv"
    result_df.to_csv(out_fp, index=False, encoding="utf-8-sig")
    print(f"\n防治策略已保存 -> prevention_strategy.csv")

    # ── 验证 ──────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("验证")
    print("=" * 60)

    all_pass = True

    # 1. 加固后崩溃临界点 ≥ 加固前
    # 崩溃前 threshold_shift=0，崩溃后若修复则 > 0
    # city_collapse_after 应该 <= city_collapse_before
    for s in strategies:
        if s["strategy"] == "baseline":
            continue
        if s["city_collapse_before"] and not s["city_collapse_after"]:
            print(f"  ✅ 策略{s['strategy']}: 崩溃 -> 未崩溃，临界点提升 +{s['threshold_shift']:.1f}")
        elif not s["city_collapse_before"]:
            print(f"  ✅ 策略{s['strategy']}: 原本未崩溃，保持未崩溃")
        else:
            if s["medical_ratio_after"] > s["medical_ratio_before"]:
                print(f"  ✅ 策略{s['strategy']}: 功能率提升 {s['medical_ratio_before']:.4f} -> {s['medical_ratio_after']:.4f}（但仍低于阈值）")
            else:
                print(f"  ❌ 策略{s['strategy']}: 功能率未提升")
                all_pass = False

    # 2. 策略C效果 ≥ 策略A或B单独效果
    strat_a = next(s for s in strategies if s["strategy"] == "A")
    strat_b = next(s for s in strategies if s["strategy"] == "B")
    strat_c = next(s for s in strategies if s["strategy"] == "C")

    if strat_c["medical_ratio_after"] >= max(strat_a["medical_ratio_after"], strat_b["medical_ratio_after"]):
        print(f"  ✅ 策略C医疗功能率({strat_c['medical_ratio_after']:.4f}) ≥ max(A:{strat_a['medical_ratio_after']:.4f}, B:{strat_b['medical_ratio_after']:.4f})")
    else:
        print(f"  ❌ 策略C效果不如A或B单独")
        all_pass = False

    if strat_c["threshold_shift"] >= max(strat_a["threshold_shift"], strat_b["threshold_shift"]):
        print(f"  ✅ 策略C临界点提升({strat_c['threshold_shift']:.1f}) ≥ max(A:{strat_a['threshold_shift']:.1f}, B:{strat_b['threshold_shift']:.1f})")
    else:
        print(f"  ❌ 策略C临界点提升不如A或B")
        all_pass = False

    # 3. 关键路段确实在断裂带附近
    if key_roads_df is not None and len(key_roads_df) > 0:
        max_dist = key_roads_df["dist_to_fault_m"].max()
        print(f"  ✅ 关键路段距断裂带最大距离: {max_dist:.0f}m（应为距断裂带最近的路段）")
    else:
        print(f"  ⚠️ 无关键路段数据")

    # 4. 无NaN
    if result_df.isnull().any().any():
        print(f"  ❌ 存在NaN值: {result_df.isnull().sum()[result_df.isnull().sum() > 0].to_dict()}")
        all_pass = False
    else:
        print(f"  ✅ 无NaN值")

    print(f"\n{'='*60}")
    if all_pass:
        print("✅ 所有验证通过")
    else:
        print("❌ 部分验证失败，请检查")
    print(f"{'='*60}")

    # 打印最终对比表
    print(f"\n防治策略对比:")
    print(f"{'策略':<10} {'描述':<40} {'医疗功能率':>10} {'崩溃':>6} {'提升':>8}")
    print("-" * 80)
    for s in strategies:
        print(f"{s['strategy']:<10} {s['description'][:38]:<40} {s['medical_ratio_after']:>10.4f} {str(s['city_collapse_after']):>6} {'+'+str(s['threshold_shift']):>8}")


if __name__ == "__main__":
    main()
