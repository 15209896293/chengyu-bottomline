"""
step11_nightlight_population.py — 面积加权法将区县人口GDP分配到网格级

面积加权法（NPP-VIIRS 夜间灯光数据的回退方案）：
  1. 读取区县级人口GDP统计 (population_gdp_summary.csv)
  2. 读取 500m 网格 (grid_base.geojson)，转 EPSG:4527 计算每个网格面积
  3. 按区县分组，面积加权分配人口和 GDP 到网格
  4. hospital_count 作为城市密度修正因子（修正后归一化，总和不变）
  5. 如存在 nightlight_hefei.tif，优先用灯光亮度作为权重（预留接口）

输出: grid_population_gdp.csv
  cell_id, district, area_m2, population, gdp_yi, hospital_count, dist_to_epi_km
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
CRS_PROJ = "EPSG:4527"      # CGCS2000 投影坐标(3度带39, 合肥所在)
SEED = 42

# 城区/郊区分类（用于验证密度梯度）
URBAN_DISTRICTS = {"瑶海区", "庐阳区", "蜀山区", "包河区"}
SUBURBAN_DISTRICTS = {"长丰县", "肥东县", "肥西县", "庐江县", "巢湖市"}

# 医院密度修正因子系数：修正因子 = 1 + ALPHA * hospital_count
HOSPITAL_CORRECTION_ALPHA = 0.1


# ── 夜间灯光数据接口（预留） ─────────────────────────────
def load_nightlight_data(grid_gdf, tif_path=None):
    """加载夜间灯光数据并按网格质心采样。

    检查 nightlight_hefei.tif 是否存在：
      - 存在：用 rasterio 读取，按网格质心采样，返回灯光亮度数组
      - 不存在：返回 None，调用方使用面积加权回退方案

    Parameters
    ----------
    grid_gdf : GeoDataFrame
        网格数据（EPSG:4490），用于提取质心坐标
    tif_path : Path, optional
        夜间灯光 TIFF 路径，默认 DATA_DIR / "nightlight_hefei.tif"

    Returns
    -------
    np.ndarray or None
        每个网格的灯光亮度值（与 grid_gdf 行对齐）；不可用时返回 None
    """
    if tif_path is None:
        tif_path = DATA_DIR / "nightlight_hefei.tif"
    tif_path = Path(tif_path)

    if not tif_path.exists():
        print(f"  夜间灯光数据不存在: {tif_path.name}")
        print(f"  -> 使用面积加权回退方案")
        return None

    try:
        import rasterio
        from rasterio.warp import transform as warp_transform
    except ImportError:
        print(f"  rasterio 未安装 -> 使用面积加权回退方案")
        return None

    print(f"  读取夜间灯光数据: {tif_path.name}")
    with rasterio.open(tif_path) as src:
        # 网格质心（EPSG:4490 地理坐标）
        centroids = grid_gdf.geometry.centroid
        xs = np.array([pt.x for pt in centroids])
        ys = np.array([pt.y for pt in centroids])

        # 若 TIFF 坐标系非 WGS84/CGCS2000，转换质心坐标
        tif_crs = src.crs
        if tif_crs is not None and tif_crs.to_epsg() not in (4326, 4490):
            xs, ys = warp_transform("EPSG:4326", tif_crs, xs, ys)

        # 按质心采样
        coords = list(zip(xs, ys))
        values = np.array([val[0] for val in src.sample(coords)], dtype=float)

    # 灯光亮度非负
    values = np.clip(values, 0, None)
    n_valid = int((values > 0).sum())
    print(f"  有效灯光网格: {n_valid}/{len(values)}")

    if n_valid == 0:
        print(f"  所有灯光值为 0 -> 使用面积加权回退方案")
        return None

    return values


# ── 主流程 ─────────────────────────────────────────────
def main():
    np.random.seed(SEED)

    print("=" * 60)
    print("Step 11: 面积加权法分配人口 GDP 到网格")
    print("=" * 60)

    # ── 1. 读取区县人口 GDP ──────────────────────────────
    print("\n[1/5] 读取区县人口 GDP 数据...")
    pop_gdp = pd.read_csv(DATA_DIR / "population_gdp_summary.csv")
    print(f"  区县数: {len(pop_gdp)}")
    print(f"  总人口: {pop_gdp['population_wan'].sum():.1f} 万人")
    print(f"  总 GDP: {pop_gdp['gdp_yi'].sum():.1f} 亿元")

    # ── 2. 读取网格并计算面积 ────────────────────────────
    print("\n[2/5] 读取网格数据并计算面积...")
    grid = gpd.read_file(DATA_DIR / "grid_base.geojson")
    print(f"  网格数: {len(grid)}")
    print(f"  CRS: {grid.crs}")

    # 转 EPSG:4527 计算面积（投影坐标系单位为米）
    grid_proj = grid.to_crs(CRS_PROJ)
    grid["area_m2"] = grid_proj.geometry.area
    print(f"  平均面积: {grid['area_m2'].mean():.0f} m2")
    print(f"  面积范围: {grid['area_m2'].min():.0f} ~ {grid['area_m2'].max():.0f} m2")

    # ── 3. 尝试加载夜间灯光数据 ──────────────────────────
    print("\n[3/5] 检查夜间灯光数据...")
    nightlight = load_nightlight_data(grid)
    use_nightlight = nightlight is not None

    # 将灯光值附加到 grid（便于按区县切片对齐）
    if use_nightlight:
        grid["nightlight"] = nightlight
    else:
        grid["nightlight"] = 0.0

    # ── 4. 按区县面积加权分配 ────────────────────────────
    print("\n[4/5] 按区县分配人口 GDP...")
    method = "夜间灯光权重" if use_nightlight else "面积加权"
    print(f"  分配方法: {method} + 医院密度修正 (alpha={HOSPITAL_CORRECTION_ALPHA})")

    all_results = []

    for _, row in pop_gdp.iterrows():
        district = row["district"]
        pop_total = row["population_wan"] * 10000  # 万人 -> 人
        gdp_total = row["gdp_yi"]                  # 亿元

        mask = grid["district"] == district
        grids = grid[mask]

        n_grids = len(grids)
        if n_grids == 0:
            print(f"  [WARN] {district}: 无匹配网格，跳过")
            continue

        areas = grids["area_m2"].values
        hospital = grids["hospital_count"].values
        nl = grids["nightlight"].values

        # ── 基础权重 ──
        if use_nightlight:
            # 夜间灯光权重 = 灯光亮度 x 面积
            # 灯光值为 0 的网格用面积 * 0.01 作为回退（保持极小权重）
            base_weights = np.where(nl > 0, nl * areas, areas * 0.01)
        else:
            # 纯面积加权
            base_weights = areas.copy()

        # ── 医院密度修正 ──
        # 修正因子 = 1 + 0.1 * hospital_count
        # 有医院的网格（城市区域）适当增加人口权重
        correction = 1.0 + HOSPITAL_CORRECTION_ALPHA * hospital
        weights = base_weights * correction

        # ── 归一化（使区县内权重之和 = 1，保证总和不变）──
        total_weight = weights.sum()
        if total_weight > 0:
            weights = weights / total_weight
        else:
            # 极端情况：均匀分配
            weights = np.ones(n_grids) / n_grids

        # ── 分配 ──
        pop_grid = pop_total * weights
        gdp_grid = gdp_total * weights

        result = pd.DataFrame({
            "cell_id": grids["cell_id"].values,
            "district": district,
            "area_m2": np.round(areas, 2),
            "population": pop_grid,
            "gdp_yi": gdp_grid,
            "hospital_count": hospital.astype(int),
            "dist_to_epi_km": grids["dist_to_epi_km"].values,
        })
        all_results.append(result)

        n_hosp_grids = int((hospital > 0).sum())
        avg_pop = pop_grid.mean()
        print(f"  {district}: {n_grids} 网格, 人口={pop_total/10000:.1f} 万, "
              f"网格均值={avg_pop:.1f} 人, 医院网格={n_hosp_grids}")

    result_df = pd.concat(all_results, ignore_index=True)

    # ── 5. 保存输出 ──────────────────────────────────────
    print("\n[5/5] 保存结果...")
    result_df["population"] = result_df["population"].round(2)
    result_df["gdp_yi"] = result_df["gdp_yi"].round(6)
    result_df["dist_to_epi_km"] = result_df["dist_to_epi_km"].round(4)

    out_path = DATA_DIR / "grid_population_gdp.csv"
    result_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"  输出: {out_path}")
    print(f"  总行数: {len(result_df)}")

    # ── 验证 ─────────────────────────────────────────────
    validate(result_df, pop_gdp)


# ── 验证 ───────────────────────────────────────────────
def validate(result_df, pop_gdp):
    """验证分配结果，不通过则打印失败原因。"""
    print("\n" + "=" * 60)
    print("验证")
    print("=" * 60)

    all_pass = True

    # 1. 各区县网格人口之和 = 区县总人口（允许 1% 误差）
    print("\n[1] 区县人口守恒验证 (允许 1% 误差)...")
    for _, row in pop_gdp.iterrows():
        district = row["district"]
        target = row["population_wan"] * 10000
        actual = result_df.loc[result_df["district"] == district, "population"].sum()
        if target > 0:
            err = abs(actual - target) / target
        else:
            err = 0.0
        ok = err < 0.01
        if not ok:
            all_pass = False
        print(f"  {district}: 目标={target:.0f}, 实际={actual:.0f}, "
              f"误差={err * 100:.2f}% [{'OK' if ok else 'FAIL'}]")

    # 2. 城区网格人口密度 > 郊区网格人口密度
    print("\n[2] 城区/郊区人口密度验证...")
    urban = result_df[result_df["district"].isin(URBAN_DISTRICTS)]
    suburban = result_df[result_df["district"].isin(SUBURBAN_DISTRICTS)]

    if len(urban) > 0 and len(suburban) > 0:
        urban_density = urban["population"].sum() / (urban["area_m2"].sum() / 1e6)
        suburban_density = suburban["population"].sum() / (suburban["area_m2"].sum() / 1e6)
        ok = urban_density > suburban_density
        if not ok:
            all_pass = False
        print(f"  城区密度: {urban_density:.0f} 人/km2")
        print(f"  郊区密度: {suburban_density:.0f} 人/km2")
        print(f"  [{'OK' if ok else 'FAIL'}]")
    else:
        print(f"  [SKIP] 城区网格={len(urban)}, 郊区网格={len(suburban)}")

    # 3. 有医院的网格人口 > 无医院的网格平均人口
    print("\n[3] 医院网格人口验证...")
    with_hospital = result_df[result_df["hospital_count"] > 0]
    without_hospital = result_df[result_df["hospital_count"] == 0]

    if len(with_hospital) > 0 and len(without_hospital) > 0:
        avg_with = with_hospital["population"].mean()
        avg_without = without_hospital["population"].mean()
        ok = avg_with > avg_without
        if not ok:
            all_pass = False
        print(f"  有医院网格平均人口: {avg_with:.1f} 人 ({len(with_hospital)} 个网格)")
        print(f"  无医院网格平均人口: {avg_without:.1f} 人 ({len(without_hospital)} 个网格)")
        print(f"  [{'OK' if ok else 'FAIL'}]")
    else:
        print(f"  [SKIP] 有医院={len(with_hospital)}, 无医院={len(without_hospital)}")

    # 4. 检查无 NaN 值
    print("\n[4] NaN 检查...")
    nan_count = int(result_df[["population", "gdp_yi", "area_m2"]].isna().sum().sum())
    ok = nan_count == 0
    if not ok:
        all_pass = False
    print(f"  NaN 数量: {nan_count} [{'OK' if ok else 'FAIL'}]")

    # ── 总结 ──
    print("\n" + "-" * 40)
    if all_pass:
        print("[PASS] 所有验证通过")
    else:
        print("[FAIL] 部分验证未通过，请检查上述失败项")
    print("-" * 40)

    return all_pass


if __name__ == "__main__":
    main()
