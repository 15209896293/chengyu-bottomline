"""
step13_resilience_index.py — 四维韧性指数计算与可视化数据输出

对每个震级 M{X}（5.0~7.5），从可达性、暴露、路网阻断数据中提取四个维度，
归一化后加权求和得到综合韧性指数，并判定城市崩溃临界点。

四维定义：
  医疗覆盖 (0.3) — (正常可达 + 0.5×可达但受限) / 总医院数
  避难比例 (0.2) — (正常可达容量 + 0.5×受限容量) / 受影响人口
  道路连通 (0.3) — 1 - 0.8×完全阻断比 - 0.3×严重损伤比
  灾害安全 (0.2) — (正常可达 + 0.5×可达但受限) / 危险源总数

输出：
  resilience_index_M{X}.csv  — 单震级四维明细
  resilience_summary.csv     — 全震级汇总
"""
import os
import sys
import traceback
from pathlib import Path

# ── GDAL/PROJ 路径（必须在导入 geopandas 前设置）──
LIB = Path("F:/anaconda/envs/zhenmai/Library/share")
os.environ.setdefault("GDAL_DATA", str(LIB / "gdal"))
os.environ.setdefault("PROJ_LIB", str(LIB / "proj"))

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import geopandas as gpd

# ── 全局配置 ──
SEED = 42
np.random.seed(SEED)

DATA_DIR = Path(__file__).resolve().parent.parent / "数据文件"
MAGNITUDES = [5.0, 5.5, 6.0, 6.5, 7.0, 7.5]

# 四维权重
W_MEDICAL = 0.3
W_SHELTER = 0.2
W_TRANSPORT = 0.3
W_SAFETY = 0.2

# 可达性 → 分数映射
ACC_SCORE = {"正常可达": 1.0, "可达但受限": 0.5, "不可达": 0.0}

# 崩溃阈值（collapse_threshold.csv 不存在时使用）
COLLAPSE_THRESHOLD = 0.5

CSV_ENCODING = "utf-8-sig"


# ═══════════════════════════════════════════════════════════
# 维度计算
# ═══════════════════════════════════════════════════════════
def compute_medical(mag):
    """医疗覆盖维度：可达医院 / 总医院。

    (正常可达 + 0.5×可达但受限) / 总数
    """
    df = pd.read_csv(DATA_DIR / f"accessibility_M{mag:.1f}.csv", encoding=CSV_ENCODING)
    total = len(df)
    if total == 0:
        return 1.0
    vc = df["accessibility"].value_counts()
    score = sum(ACC_SCORE.get(k, 0.0) * v for k, v in vc.items())
    return float(np.clip(score / total, 0.0, 1.0))


def compute_shelter(mag, affected_pop, capacity_map):
    """避难比例维度：可达避难所容量 / 需转移人口。

    (正常可达容量 + 0.5×受限容量) / affected_population
    若 affected_population == 0，返回 1.0（无避难需求）。
    """
    df = pd.read_csv(DATA_DIR / f"accessibility_facilities_M{mag:.1f}.csv", encoding=CSV_ENCODING)
    shelters = df[df["type"] == "避难所"]

    if len(shelters) == 0:
        return 1.0 if affected_pop == 0 else 0.0

    # 累加加权容量
    reachable_cap = 0.0
    for _, row in shelters.iterrows():
        cap = capacity_map.get(row["name"], 0)
        weight = ACC_SCORE.get(row["accessibility"], 0.0)
        reachable_cap += cap * weight

    if affected_pop == 0:
        return 1.0

    return float(np.clip(reachable_cap / affected_pop, 0.0, 1.0))


def compute_transport(mag):
    """道路连通维度：路网连通度。

    1 - 0.8×(完全阻断比) - 0.3×(严重损伤比)
    """
    gdf = gpd.read_file(DATA_DIR / f"road_blocked_M{mag:.1f}.geojson")
    total = len(gdf)
    if total == 0:
        return 1.0

    full_ratio = int((gdf["block_level"] == "完全阻断").sum()) / total
    severe_ratio = int((gdf["block_level"] == "严重损伤").sum()) / total

    transport = 1.0 - 0.8 * full_ratio - 0.3 * severe_ratio
    return float(np.clip(transport, 0.0, 1.0))


def compute_safety(mag):
    """灾害安全维度：可达危险源管控率。

    (正常可达 + 0.5×可达但受限) / 危险源总数
    """
    df = pd.read_csv(DATA_DIR / f"accessibility_facilities_M{mag:.1f}.csv", encoding=CSV_ENCODING)
    hazards = df[df["type"] == "危险源"]

    total = len(hazards)
    if total == 0:
        return 1.0
    vc = hazards["accessibility"].value_counts()
    score = sum(ACC_SCORE.get(k, 0.0) * v for k, v in vc.items())
    return float(np.clip(score / total, 0.0, 1.0))


# ═══════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════
def get_affected_population(mag):
    """从暴露汇总获取受影响人口总数。"""
    df = pd.read_csv(DATA_DIR / f"exposure_summary_M{mag:.1f}.csv", encoding=CSV_ENCODING)
    return int(df["affected_population"].sum())


def load_shelter_capacity():
    """加载避难所容量映射 {name: capacity}。"""
    gdf = gpd.read_file(DATA_DIR / "facilities_shelters.geojson")
    return dict(zip(gdf["name"], gdf["capacity"]))


def load_collapse_threshold():
    """加载崩溃临界点数据。不存在则返回 None。"""
    path = DATA_DIR / "collapse_threshold.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, encoding=CSV_ENCODING)
    df["magnitude"] = df["magnitude"].astype(float)
    if "city_collapse" in df.columns:
        raw = df["city_collapse"].astype(str).str.strip().str.lower()
        df["city_collapse"] = raw.isin(["true", "1", "yes"])
    return df


def determine_collapse(mag, resilience, collapse_df):
    """判定城市是否崩溃。

    优先使用 collapse_threshold.csv；不存在则以韧性指数 < 阈值 判定。
    """
    if collapse_df is not None:
        row = collapse_df[collapse_df["magnitude"] == mag]
        if len(row) > 0:
            return bool(row.iloc[0]["city_collapse"])
    return resilience < COLLAPSE_THRESHOLD


# ═══════════════════════════════════════════════════════════
# 单震级韧性计算
# ═══════════════════════════════════════════════════════════
def compute_resilience(mag, capacity_map, collapse_df):
    """计算单个震级的四维韧性指数。"""
    medical = compute_medical(mag)
    affected_pop = get_affected_population(mag)
    shelter = compute_shelter(mag, affected_pop, capacity_map)
    transport = compute_transport(mag)
    safety = compute_safety(mag)

    resilience = (
        W_MEDICAL * medical
        + W_SHELTER * shelter
        + W_TRANSPORT * transport
        + W_SAFETY * safety
    )
    resilience = float(np.clip(resilience, 0.0, 1.0))
    city_collapse = determine_collapse(mag, resilience, collapse_df)

    return {
        "medical": medical,
        "shelter": shelter,
        "transport": transport,
        "safety": safety,
        "resilience": resilience,
        "city_collapse": city_collapse,
    }


# ═══════════════════════════════════════════════════════════
# 输出
# ═══════════════════════════════════════════════════════════
def save_resilience_csv(mag, result):
    """输出单震级韧性指数明细 CSV。"""
    rows = [
        {
            "dimension": "医疗覆盖",
            "value": round(result["medical"], 4),
            "weight": W_MEDICAL,
            "weighted_value": round(W_MEDICAL * result["medical"], 4),
        },
        {
            "dimension": "避难比例",
            "value": round(result["shelter"], 4),
            "weight": W_SHELTER,
            "weighted_value": round(W_SHELTER * result["shelter"], 4),
        },
        {
            "dimension": "道路连通",
            "value": round(result["transport"], 4),
            "weight": W_TRANSPORT,
            "weighted_value": round(W_TRANSPORT * result["transport"], 4),
        },
        {
            "dimension": "灾害安全",
            "value": round(result["safety"], 4),
            "weight": W_SAFETY,
            "weighted_value": round(W_SAFETY * result["safety"], 4),
        },
        {
            "dimension": "综合韧性指数",
            "value": 1.0,
            "weight": 1.0,
            "weighted_value": round(result["resilience"], 4),
        },
    ]
    df = pd.DataFrame(rows)
    out_path = DATA_DIR / f"resilience_index_M{mag:.1f}.csv"
    df.to_csv(out_path, index=False, encoding=CSV_ENCODING)
    return out_path


def save_summary(summary_rows):
    """输出全震级汇总 CSV。"""
    df = pd.DataFrame(summary_rows, columns=[
        "magnitude", "medical", "shelter", "transport", "safety",
        "resilience_index", "city_collapse",
    ])
    out_path = DATA_DIR / "resilience_summary.csv"
    df.to_csv(out_path, index=False, encoding=CSV_ENCODING)
    return out_path


# ═══════════════════════════════════════════════════════════
# 验证
# ═══════════════════════════════════════════════════════════
def verify(results):
    """验证输出正确性，失败则打印原因。"""
    ok = True
    reasons = []
    mags = sorted(results.keys())

    # 1. 韧性指数随震级递减（允许相等）
    for i in range(len(mags) - 1):
        m1, m2 = mags[i], mags[i + 1]
        r1 = results[m1]["resilience"]
        r2 = results[m2]["resilience"]
        if r1 < r2 - 1e-9:
            ok = False
            reasons.append(
                f"韧性指数未随震级递减: M{m1}={r1:.4f} < M{m2}={r2:.4f}"
            )
    if ok:
        vals = [f"M{m}={results[m]['resilience']:.4f}" for m in mags]
        print(f"  [OK] 韧性指数随震级递减: {', '.join(vals)}")

    # 2. 四维指标均在 0~1 之间
    dim_ok = True
    for m in mags:
        for dim in ["medical", "shelter", "transport", "safety"]:
            val = results[m][dim]
            if pd.isna(val) or val < 0.0 or val > 1.0:
                ok = False
                dim_ok = False
                reasons.append(f"M{m} {dim}={val} 超出 [0,1] 范围")
    if dim_ok:
        print(f"  [OK] 四维指标均在 [0,1] 范围内")

    # 3. 韧性指数与崩溃临界点一致（指数低则崩溃）
    collapsed = [m for m in mags if results[m]["city_collapse"]]
    not_collapsed = [m for m in mags if not results[m]["city_collapse"]]
    collapse_ok = True
    if collapsed and not_collapsed:
        max_collapsed_res = max(results[m]["resilience"] for m in collapsed)
        min_not_collapsed_res = min(results[m]["resilience"] for m in not_collapsed)
        if max_collapsed_res > min_not_collapsed_res + 1e-9:
            ok = False
            collapse_ok = False
            reasons.append(
                f"崩溃一致性失败: 崩溃最大韧性 {max_collapsed_res:.4f} "
                f"> 未崩溃最小韧性 {min_not_collapsed_res:.4f}"
            )
    # 崩溃单调性：一旦崩溃，更高震级也应崩溃
    for i in range(len(mags) - 1):
        m1, m2 = mags[i], mags[i + 1]
        if not results[m1]["city_collapse"] and results[m2]["city_collapse"]:
            continue  # F→T 正常
        if results[m1]["city_collapse"] and not results[m2]["city_collapse"]:
            ok = False
            collapse_ok = False
            reasons.append(
                f"崩溃非单调: M{m1}=崩溃 但 M{m2}=未崩溃"
            )
    if collapse_ok:
        print(
            f"  [OK] 崩溃一致性: "
            f"崩溃 {len(collapsed)} 个震级, 未崩溃 {len(not_collapsed)} 个"
        )

    # 4. 无 NaN 值
    nan_ok = True
    for m in mags:
        for dim in ["medical", "shelter", "transport", "safety", "resilience"]:
            if pd.isna(results[m][dim]):
                ok = False
                nan_ok = False
                reasons.append(f"M{m} {dim} 为 NaN")
    if nan_ok:
        print(f"  [OK] 无 NaN 值")

    if ok:
        print("验证通过")
    else:
        print("验证失败:")
        for r in reasons:
            print(f"  - {r}")
    return ok


# ═══════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════
def main():
    print("=" * 60)
    print("step13 四维韧性指数计算")
    print("=" * 60)

    # 加载避难所容量映射
    try:
        capacity_map = load_shelter_capacity()
        print(f"  避难所容量映射: {len(capacity_map)} 个")
    except Exception as e:
        print(f"[致命] 加载避难所容量失败: {e}")
        traceback.print_exc()
        return

    # 加载崩溃临界点
    collapse_df = load_collapse_threshold()
    if collapse_df is not None:
        print(f"  已加载 collapse_threshold.csv ({len(collapse_df)} 行)")
    else:
        print(
            f"  collapse_threshold.csv 不存在，"
            f"独立计算崩溃阈值 (resilience < {COLLAPSE_THRESHOLD})"
        )

    # 逐震级计算
    results = {}
    summary_rows = []
    errors = []

    for mag in MAGNITUDES:
        try:
            print(f"\n{'─' * 40}")
            print(f"处理 M{mag:.1f} ...")
            result = compute_resilience(mag, capacity_map, collapse_df)
            results[mag] = result

            out_path = save_resilience_csv(mag, result)

            print(f"  医疗覆盖: {result['medical']:.4f}  (权重 {W_MEDICAL})")
            print(f"  避难比例: {result['shelter']:.4f}  (权重 {W_SHELTER})")
            print(f"  道路连通: {result['transport']:.4f}  (权重 {W_TRANSPORT})")
            print(f"  灾害安全: {result['safety']:.4f}  (权重 {W_SAFETY})")
            print(f"  综合韧性指数: {result['resilience']:.4f}")
            print(f"  城市崩溃: {result['city_collapse']}")
            print(f"  保存: {out_path.name}")

            summary_rows.append({
                "magnitude": mag,
                "medical": round(result["medical"], 4),
                "shelter": round(result["shelter"], 4),
                "transport": round(result["transport"], 4),
                "safety": round(result["safety"], 4),
                "resilience_index": round(result["resilience"], 4),
                "city_collapse": result["city_collapse"],
            })
        except Exception as e:
            print(f"[错误] M{mag:.1f} 处理失败: {e}")
            traceback.print_exc()
            errors.append(f"M{mag:.1f}: {e}")

    # 输出汇总
    print(f"\n{'─' * 40}")
    if summary_rows:
        summary_path = save_summary(summary_rows)
        print(f"汇总文件已保存: {summary_path.name}")
        print(
            pd.DataFrame(summary_rows).to_string(index=False)
        )

    # 验证
    print(f"\n{'─' * 40}")
    print("验证输出 ...")
    if results:
        try:
            verify(results)
        except Exception as e:
            print(f"[错误] 验证过程异常: {e}")
            traceback.print_exc()

    # 汇总
    print(f"\n{'=' * 60}")
    if results:
        print(f"完成 {len(results)}/{len(MAGNITUDES)} 个震级")
    if errors:
        print(f"失败震级: {errors}")
    print("=" * 60)


if __name__ == "__main__":
    main()
