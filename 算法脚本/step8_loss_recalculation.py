"""
step8_loss_recalculation.py — 基于网格人口和GDP的地震损失重算

替换旧的无意义"医院数×损失率"算法，使用区县统计年鉴数据按网格面积加权
分配人口和GDP，再结合烈度计算真实的人口暴露与经济损失。

输入:
  - population_gdp_summary.csv   区县人口(万人)和GDP(亿元)
  - grid_base.geojson (EPSG:4490)  500m网格，含cell_id/district/geometry
  - grid_intensity_M{X}.csv     各震级的烈度数据

输出 (覆盖旧文件):
  - loss_estimate_M{X}.csv      区县损失汇总
  - exposure_summary_M{X}.csv   区县暴露度汇总
"""
import os
from pathlib import Path

LIB = Path("F:/anaconda/envs/zhenmai/Library/share")
os.environ.setdefault("GDAL_DATA", str(LIB / "gdal"))
os.environ.setdefault("PROJ_LIB", str(LIB / "proj"))

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import geopandas as gpd

# ── 配置 ────────────────────────────────────────────────
DATA_DIR = Path(__file__).resolve().parent.parent / "数据文件"
CRS_GEO = "EPSG:4490"       # CGCS2000 地理坐标
CRS_PROJ = "EPSG:4527"      # CGCS2000 3度带投影(合肥所在)
MAGNITUDES = [5.0, 5.5, 6.0, 6.5, 7.0, 7.5]
SEED = 42


def loss_rate_from_intensity(i):
    """烈度→损失率分档（与现有算法一致）"""
    if i < 5:
        return 0.0
    elif i < 7:
        return 0.05
    elif i < 8:
        return 0.20
    else:
        return 0.50


def main():
    np.random.seed(SEED)

    print("=" * 60)
    print("Step 8: 基于网格人口和GDP的损失重算")
    print("=" * 60)

    # ── 1. 读取区县人口和GDP ──────────────────────────────
    summary_csv = pd.read_csv(DATA_DIR / "population_gdp_summary.csv")
    print(f"\n读取区县统计: {len(summary_csv)} 个区县")
    print(f"  总人口: {summary_csv['population_wan'].sum():.1f} 万人")
    print(f"  总GDP: {summary_csv['gdp_yi'].sum():.1f} 亿元")

    # 区县→总量映射（单位转换：万人→人，亿元→元）
    district_data = {}
    for _, row in summary_csv.iterrows():
        district_data[row["district"]] = {
            "total_pop": row["population_wan"] * 10000,   # 万人 → 人
            "total_gdp": row["gdp_yi"] * 1e8,              # 亿元 → 元
        }

    # ── 2. 读取网格并计算面积 ──────────────────────────────
    print("\n读取网格数据...")
    grid = gpd.read_file(DATA_DIR / "grid_base.geojson")
    print(f"  网格总数: {len(grid)}")
    print(f"  CRS: {grid.crs}")

    # 转投影坐标系计算每个网格面积(m²)
    grid_proj = grid.to_crs(CRS_PROJ)
    grid_proj["area_m2"] = grid_proj.geometry.area
    print(f"  平均网格面积: {grid_proj['area_m2'].mean():.1f} m²")
    print(f"  网格面积范围: {grid_proj['area_m2'].min():.1f} ~ {grid_proj['area_m2'].max():.1f} m²")

    # ── 3. 按网格面积加权分配人口和GDP ────────────────────
    print("\n按网格面积加权分配人口和GDP...")
    grid_proj["grid_pop"] = 0.0
    grid_proj["grid_gdp"] = 0.0

    for district, data in district_data.items():
        mask = grid_proj["district"] == district
        n_cells = int(mask.sum())
        if n_cells == 0:
            print(f"  [警告] {district} 无网格数据，跳过")
            continue
        total_area = grid_proj.loc[mask, "area_m2"].sum()
        # 面积占比 = 网格面积 / 区县网格总面积
        area_share = grid_proj.loc[mask, "area_m2"] / total_area
        grid_proj.loc[mask, "grid_pop"] = data["total_pop"] * area_share
        grid_proj.loc[mask, "grid_gdp"] = data["total_gdp"] * area_share
        print(f"  {district}: {n_cells} 格, 面积{total_area/1e6:.2f} km², "
              f"人口{data['total_pop']/10000:.1f}万, GDP{data['total_gdp']/1e8:.1f}亿")

    # 验证分配总量
    total_pop = grid_proj["grid_pop"].sum()
    total_gdp = grid_proj["grid_gdp"].sum()
    print(f"\n  分配总人口: {total_pop/10000:.1f} 万人")
    print(f"  分配总GDP: {total_gdp/1e8:.1f} 亿元")

    # 提取网格级分配结果
    grid_alloc = grid_proj[["cell_id", "district", "grid_pop", "grid_gdp"]].copy()
    grid_alloc["cell_id"] = grid_alloc["cell_id"].astype(np.int64)

    # ── 4. 按震级计算损失 ────────────────────────────────
    all_loss = {}  # mag → loss DataFrame

    for mag in MAGNITUDES:
        mag_str = f"M{mag:.1f}"
        print(f"\n{'─' * 40}")
        print(f"处理震级: {mag_str}")

        # 读取烈度数据
        intensity_df = pd.read_csv(DATA_DIR / f"grid_intensity_{mag_str}.csv")
        intensity_df["cell_id"] = intensity_df["cell_id"].astype(np.int64)
        print(f"  烈度网格数: {len(intensity_df)}")

        # 合并网格人口、GDP和烈度（以烈度表为基准左连接）
        merged = intensity_df.merge(grid_alloc, on="cell_id", how="left")

        # 检查合并完整性
        n_nan = merged["grid_pop"].isna().sum()
        if n_nan > 0:
            print(f"  [警告] {n_nan} 个网格无人口数据，填充为0")
        merged[["grid_pop", "grid_gdp"]] = merged[["grid_pop", "grid_gdp"]].fillna(0.0)
        merged["district"] = merged["district"].fillna("未知")

        # 重新计算损失率（确保与函数一致）
        merged["loss_rate"] = merged["intensity"].apply(loss_rate_from_intensity)

        # 网格级损失计算
        merged["affected_pop"] = merged["grid_pop"] * merged["loss_rate"]
        merged["economic_loss"] = merged["grid_gdp"] * merged["loss_rate"]
        merged["exposed_pop"] = np.where(merged["intensity"] >= 5.0,
                                         merged["grid_pop"], 0.0)
        # 人口×烈度（用于加权平均）
        merged["pop_x_intensity"] = merged["grid_pop"] * merged["intensity"]

        # ── 按区县汇总 ──────────────────────────────────────
        agg = merged.groupby("district").agg(
            total_population=("grid_pop", "sum"),
            exposed_population=("exposed_pop", "sum"),
            affected_population=("affected_pop", "sum"),
            total_gdp_yuan=("grid_gdp", "sum"),
            economic_loss_yuan=("economic_loss", "sum"),
            grid_count=("cell_id", "count"),
            pop_x_intensity_sum=("pop_x_intensity", "sum"),
        ).reset_index()

        # 人口加权平均烈度
        agg["avg_intensity"] = np.where(
            agg["total_population"] > 0,
            agg["pop_x_intensity_sum"] / agg["total_population"],
            0.0,
        )

        # 转换单位并格式化
        agg["total_population"] = agg["total_population"].round(0).astype(int)
        agg["exposed_population"] = agg["exposed_population"].round(0).astype(int)
        agg["affected_population"] = agg["affected_population"].round(0).astype(int)
        agg["total_gdp"] = (agg["total_gdp_yuan"] / 1e8).round(2)        # 元 → 亿元
        agg["economic_loss"] = (agg["economic_loss_yuan"] / 1e8).round(2)  # 元 → 亿元
        agg["avg_intensity"] = agg["avg_intensity"].round(2)
        agg["pop_loss_rate"] = np.where(
            agg["total_population"] > 0,
            agg["affected_population"] / agg["total_population"],
            0.0,
        ).round(4)
        agg["gdp_loss_rate"] = np.where(
            agg["total_gdp"] > 0,
            agg["economic_loss"] / agg["total_gdp"],
            0.0,
        ).round(4)

        # 按统计年鉴区县顺序排列
        district_order = {d: i for i, d in enumerate(summary_csv["district"])}
        agg["_order"] = agg["district"].map(district_order).fillna(99)
        agg = agg.sort_values("_order").drop(columns="_order").reset_index(drop=True)

        # ── 输出 loss_estimate_M{X}.csv ─────────────────────
        loss_cols = ["district", "total_population", "exposed_population",
                     "affected_population", "total_gdp", "economic_loss",
                     "avg_intensity", "pop_loss_rate", "gdp_loss_rate"]
        loss_df = agg[loss_cols].copy()
        loss_df.to_csv(DATA_DIR / f"loss_estimate_{mag_str}.csv",
                       index=False, encoding="utf-8-sig")
        print(f"  -> loss_estimate_{mag_str}.csv")

        # ── 输出 exposure_summary_M{X}.csv ──────────────────
        exp_cols = ["district", "total_population", "exposed_population",
                    "affected_population", "total_gdp", "economic_loss",
                    "grid_count", "avg_intensity"]
        exp_df = agg[exp_cols].copy()
        exp_df.to_csv(DATA_DIR / f"exposure_summary_{mag_str}.csv",
                      index=False, encoding="utf-8-sig")
        print(f"  -> exposure_summary_{mag_str}.csv")

        all_loss[mag] = loss_df

        # 摘要输出
        print(f"  暴露人口: {loss_df['exposed_population'].sum()/10000:.1f}万, "
              f"受影响人口: {loss_df['affected_population'].sum()/10000:.1f}万, "
              f"经济损失: {loss_df['economic_loss'].sum():.1f}亿元")

    # ── 5. 验证 ────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print("验证检查")
    print("=" * 60)
    verify(all_loss, summary_csv)

    print(f"\n全部完成！")
    print(f"输出目录: {DATA_DIR}")


def verify(all_loss, summary_csv):
    """验证计算结果的合理性，不通过则打印失败原因"""
    all_pass = True

    # 检查1: 各区县人口之和 ≈ 总人口845.5万
    total_pop = all_loss[5.0]["total_population"].sum()
    expected_pop = summary_csv["population_wan"].sum() * 10000
    diff_pct = abs(total_pop - expected_pop) / expected_pop * 100
    if diff_pct < 1.0:
        print(f"  [PASS] 人口总量检查: {total_pop/10000:.1f}万 "
              f"(期望 {expected_pop/10000:.1f}万, 偏差 {diff_pct:.2f}%)")
    else:
        print(f"  [FAIL] 人口总量检查: {total_pop/10000:.1f}万 "
              f"!= {expected_pop/10000:.1f}万 (偏差 {diff_pct:.2f}%)")
        all_pass = False

    # 检查2: M7.5的暴露人口 > M5.0的暴露人口
    exp_75 = all_loss[7.5]["exposed_population"].sum()
    exp_50 = all_loss[5.0]["exposed_population"].sum()
    if exp_75 > exp_50:
        print(f"  [PASS] 暴露人口单调性: "
              f"M7.5={exp_75/10000:.1f}万 > M5.0={exp_50/10000:.1f}万")
    else:
        print(f"  [FAIL] 暴露人口单调性: "
              f"M7.5={exp_75/10000:.1f}万 <= M5.0={exp_50/10000:.1f}万")
        all_pass = False

    # 检查3: 经济损失随震级单调递增
    losses = [all_loss[m]["economic_loss"].sum() for m in MAGNITUDES]
    monotonic = all(losses[i] < losses[i + 1] for i in range(len(losses) - 1))
    loss_str = ", ".join(f"M{m:.1f}={l:.1f}"
                         for m, l in zip(MAGNITUDES, losses))
    if monotonic:
        print(f"  [PASS] 经济损失单调递增: {loss_str}")
    else:
        print(f"  [FAIL] 经济损失未单调递增: {loss_str}")
        all_pass = False

    # 检查4: 无NaN值
    has_nan = False
    for mag in MAGNITUDES:
        if all_loss[mag].isna().any().any():
            has_nan = True
            nan_cols = all_loss[mag].columns[all_loss[mag].isna().any()].tolist()
            print(f"  [FAIL] M{mag:.1f} 存在NaN: {nan_cols}")
    if not has_nan:
        print(f"  [PASS] 无NaN值检查通过")

    if all_pass:
        print("\n  >>> 全部验证通过 <<<")
    else:
        print("\n  >>> 验证存在失败项，请检查上方输出 <<<")

    return all_pass


if __name__ == "__main__":
    main()
