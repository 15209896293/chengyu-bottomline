"""
step6b_improve_facilities.py — 检查并补强消防站、避难所、危险源设施数据

对已有真实 POI 设施数据做分布合理性补强：
  1. 读取合肥市 9 区县边界，对每类设施做空间 join 确认区县归属
  2. 过滤掉不在合肥市范围内的设施
  3. 避难所按名称关键词分配合理容量（体育/森林公园 5000-10000，游园/口袋公园 2000-3000，其他 3000-5000）
  4. 危险源（化工厂）统一 risk_level=3、buffer_radius=800
  5. 消防站统一 capacity=5 辆、coverage_radius=3000m
  6. 统计各区县设施数量；若某区县无消防站，在区县政府所在地附近补建 1 个
  7. 覆盖输出 facilities_hazards/rescue/shelters.geojson

坐标系统：EPSG:4490   随机种子：SEED=42   GeoJSON：utf-8
不修改 hefei_hospital.csv、hefei_road_graph.graphml 等原始数据文件。
"""
import os
from pathlib import Path

LIB = Path("F:/anaconda/envs/zhenmai/Library/share")
os.environ.setdefault("GDAL_DATA", str(LIB / "gdal"))
os.environ.setdefault("PROJ_LIB", str(LIB / "proj"))

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point

SEED = 42
rng = np.random.default_rng(SEED)
DATA_DIR = Path(__file__).resolve().parent.parent / "数据文件"

# 9 区县政府所在地近似坐标 (lng, lat)，用于补建消防站
DISTRICT_GOV = {
    "瑶海区": (117.309, 31.858),
    "庐阳区": (117.264, 31.879),
    "蜀山区": (117.260, 31.851),
    "包河区": (117.310, 31.795),
    "长丰县": (117.165, 32.479),
    "肥东县": (117.469, 31.887),
    "肥西县": (117.168, 31.723),
    "庐江县": (117.289, 31.233),
    "巢湖市": (117.874, 31.600),
}

# 各类设施的属性列顺序（与原文件 schema 一致）
COLS_HAZARDS = ["name", "lng", "lat", "type", "subtype", "address", "tel",
                "risk_level", "hazard_material", "buffer_radius", "id"]
COLS_RESCUE = ["name", "lng", "lat", "type", "subtype", "address", "tel",
               "capacity", "capacity_unit", "coverage_radius", "id"]
COLS_SHELTERS = ["name", "lng", "lat", "type", "subtype", "address", "tel",
                 "capacity", "id"]


# ── 辅助函数 ─────────────────────────────────────────────
def assign_shelter_capacity(name: str) -> int:
    """根据名称关键词分配避难所容量（人）"""
    n = str(name)
    if "体育" in n or "森林公园" in n:
        return int(rng.integers(5000, 10001))
    if "游园" in n or "口袋公园" in n:
        return int(rng.integers(2000, 3001))
    return int(rng.integers(3000, 5001))


def load_districts() -> gpd.GeoDataFrame:
    gdf = gpd.read_file(DATA_DIR / "hefei_districts_4490.geojson").to_crs("EPSG:4490")
    return gdf[["name", "geometry"]]


def spatial_join_district(gdf: gpd.GeoDataFrame, districts: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """空间 join 确认区县归属。返回带 district 列的 gdf（不在范围内的 district 为 NaN）。"""
    gdf = gdf.to_crs("EPSG:4490").copy()
    joined = gpd.sjoin(
        gdf,
        districts.rename(columns={"name": "district"}),
        how="left",
        predicate="within",
    )
    joined = joined.drop(columns=["index_right"], errors="ignore")
    return joined


def fix_lnglat(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """让 lng/lat 字段与 geometry 坐标一致"""
    gdf = gdf.copy()
    gdf["lng"] = gdf.geometry.x.round(6)
    gdf["lat"] = gdf.geometry.y.round(6)
    return gdf


def finalize(gdf: gpd.GeoDataFrame, prop_cols) -> gpd.GeoDataFrame:
    """重排列、重置 id、确保 schema 一致"""
    for c in prop_cols:
        if c not in gdf.columns:
            gdf[c] = np.nan
    gdf = gdf[prop_cols + ["geometry"]]
    gdf = gdf.reset_index(drop=True)
    gdf["id"] = list(range(len(gdf)))
    return gdf


def save_geojson(gdf: gpd.GeoDataFrame, fname: str):
    gdf = gdf.to_crs("EPSG:4490")
    out = DATA_DIR / fname
    gdf.to_file(out, driver="GeoJSON", encoding="utf-8")
    print(f"  已保存: {fname} ({len(gdf)} 条)")


# ── 1. 危险源 ────────────────────────────────────────────
def process_hazards(districts) -> gpd.GeoDataFrame:
    print("\n--- 危险源补强 ---")
    gdf = gpd.read_file(DATA_DIR / "facilities_hazards.geojson").to_crs("EPSG:4490")
    n0 = len(gdf)

    joined = spatial_join_district(gdf, districts)
    inside = joined["district"].notna()
    removed = joined[~inside]
    if len(removed):
        print(f"    过滤掉 {len(removed)} 个不在合肥范围内的设施:")
        for _, r in removed.head(10).iterrows():
            print(f"      - {r.get('name', '')} ({r.geometry.x:.4f},{r.geometry.y:.4f})")
    gdf = joined[inside].copy()

    # 补强属性：化工厂统一 risk_level=3、buffer_radius=800
    mask = gdf["subtype"] == "化工厂"
    gdf.loc[mask, "risk_level"] = 3
    gdf.loc[mask, "buffer_radius"] = 800

    gdf = fix_lnglat(gdf)
    gdf = finalize(gdf, COLS_HAZARDS)
    save_geojson(gdf, "facilities_hazards.geojson")
    print(f"  原始 {n0} → 保留 {len(gdf)}")
    return gdf


# ── 2. 救援力量（消防站）────────────────────────────────
def process_rescue(districts) -> gpd.GeoDataFrame:
    print("\n--- 救援力量（消防站）补强 ---")
    gdf = gpd.read_file(DATA_DIR / "facilities_rescue.geojson").to_crs("EPSG:4490")
    n0 = len(gdf)

    joined = spatial_join_district(gdf, districts)
    inside = joined["district"].notna()
    removed = joined[~inside]
    if len(removed):
        print(f"    过滤掉 {len(removed)} 个不在合肥范围内的设施:")
        for _, r in removed.head(10).iterrows():
            print(f"      - {r.get('name', '')} ({r.geometry.x:.4f},{r.geometry.y:.4f})")
    gdf = joined[inside].copy()

    # 补强属性
    gdf["capacity"] = 5
    gdf["capacity_unit"] = "辆"
    gdf["coverage_radius"] = 3000

    # 统计各区县消防站数量，缺则补建
    counts = gdf["district"].value_counts()
    print("  各区县消防站数量:")
    for d in districts["name"]:
        print(f"    {d}: {int(counts.get(d, 0))}")

    new_rows = []
    for d in districts["name"]:
        if counts.get(d, 0) == 0:
            lng, lat = DISTRICT_GOV[d]
            pt = Point(lng, lat)
            poly = districts[districts["name"] == d].geometry.iloc[0]
            if not poly.contains(pt):
                # 政府坐标不在区内，回退到多边形代表点（保证落在区内）
                pt = poly.representative_point()
                lng, lat = pt.x, pt.y
            print(f"    [补建] {d} 无消防站，在政府所在地附近新增")
            new_rows.append({
                "name": f"{d}消防救援站",
                "lng": round(lng, 6), "lat": round(lat, 6),
                "type": "救援力量", "subtype": "消防站",
                "address": f"{d}政府附近", "tel": "",
                "capacity": 5, "capacity_unit": "辆", "coverage_radius": 3000,
            })

    # 丢弃 district 列，恢复干净 schema 后再合并补建点
    gdf = gdf.drop(columns=["district"])
    gdf = fix_lnglat(gdf)

    if new_rows:
        add_df = pd.DataFrame(new_rows)
        add_gdf = gpd.GeoDataFrame(
            add_df,
            geometry=gpd.points_from_xy(add_df["lng"], add_df["lat"]),
            crs="EPSG:4490",
        )
        for c in gdf.columns:
            if c not in add_gdf.columns:
                add_gdf[c] = np.nan
        add_gdf = add_gdf[gdf.columns]
        gdf = gpd.GeoDataFrame(pd.concat([gdf, add_gdf], ignore_index=True), crs="EPSG:4490")

    gdf = fix_lnglat(gdf)
    gdf = finalize(gdf, COLS_RESCUE)
    save_geojson(gdf, "facilities_rescue.geojson")
    print(f"  原始 {n0} → 保留+补建 {len(gdf)}")
    return gdf


# ── 3. 避难所 ────────────────────────────────────────────
def process_shelters(districts) -> gpd.GeoDataFrame:
    print("\n--- 避难所补强 ---")
    gdf = gpd.read_file(DATA_DIR / "facilities_shelters.geojson").to_crs("EPSG:4490")
    n0 = len(gdf)

    joined = spatial_join_district(gdf, districts)
    inside = joined["district"].notna()
    removed = joined[~inside]
    if len(removed):
        print(f"    过滤掉 {len(removed)} 个不在合肥范围内的设施:")
        for _, r in removed.head(10).iterrows():
            print(f"      - {r.get('name', '')} ({r.geometry.x:.4f},{r.geometry.y:.4f})")
    gdf = joined[inside].drop(columns=["district"]).copy()

    # 补强属性：按名称关键词分配容量
    gdf["capacity"] = gdf["name"].apply(assign_shelter_capacity)

    gdf = fix_lnglat(gdf)
    gdf = finalize(gdf, COLS_SHELTERS)
    save_geojson(gdf, "facilities_shelters.geojson")
    print(f"  原始 {n0} → 保留 {len(gdf)}")
    # 容量分级统计
    bins = pd.cut(gdf["capacity"], bins=[0, 3000, 5000, 10001], labels=["2000-3000", "3000-5000", "5000-10000"])
    print("  容量分级:")
    for lab, cnt in bins.value_counts().sort_index().items():
        print(f"    {lab}: {cnt} 个")
    return gdf


# ── 各区县设施数量汇总 ───────────────────────────────────
def district_summary(hazards, rescue, shelters, districts):
    print("\n--- 各区县设施数量汇总 ---")
    print(f"  {'区县':<8}{'危险源':>8}{'消防站':>8}{'避难所':>8}")
    for d in districts["name"]:
        poly = districts[districts["name"] == d].geometry.iloc[0]
        h = int(hazards.geometry.within(poly).sum())
        r = int(rescue.geometry.within(poly).sum())
        s = int(shelters.geometry.within(poly).sum())
        print(f"  {d:<8}{h:>8}{r:>8}{s:>8}")


# ── 验证 ─────────────────────────────────────────────────
def validate(districts) -> bool:
    print("\n" + "=" * 60)
    print("验证")
    print("=" * 60)
    # 重新读取已保存文件，验证落盘结果
    hazards = gpd.read_file(DATA_DIR / "facilities_hazards.geojson").to_crs("EPSG:4490")
    rescue = gpd.read_file(DATA_DIR / "facilities_rescue.geojson").to_crs("EPSG:4490")
    shelters = gpd.read_file(DATA_DIR / "facilities_shelters.geojson").to_crs("EPSG:4490")
    ok = True

    # 1. 消防站分布在多个区县
    rj = gpd.sjoin(rescue, districts.rename(columns={"name": "d"}),
                   how="left", predicate="within").drop(columns=["index_right"], errors="ignore")
    n_dist = int(rj["d"].nunique())
    print(f"  [1] 消防站覆盖区县数: {n_dist}/9", end="")
    if n_dist >= 5:
        print("   PASS")
    else:
        print("   FAIL (需 >=5)"); ok = False

    # 2. 危险源距断裂带距离合理（投影到 EPSG:4527 计算米距）
    fault = gpd.read_file(DATA_DIR / "tanlu_fault_hefei_4490.geojson").to_crs("EPSG:4490")
    hz_proj = hazards.to_crs("EPSG:4527")
    fault_proj = fault.to_crs("EPSG:4527")
    # union_all() 为新版写法，旧版 geopandas 回退到 unary_union
    fault_geom = fault_proj.geometry.union_all() if hasattr(fault_proj.geometry, "union_all") \
        else fault_proj.geometry.unary_union
    dist_m = hz_proj.geometry.distance(fault_geom)
    dist_km = dist_m / 1000.0
    med = float(dist_km.median())
    mx = float(dist_km.max())
    print(f"  [2] 危险源距断裂带: 中位数 {med:.1f}km, 最大 {mx:.1f}km", end="")
    if mx < 100 and med < 50:
        print("   PASS")
    else:
        print("   FAIL (距离不合理)"); ok = False

    # 3. 避难所容量在 2000~10000 人
    cap = shelters["capacity"]
    print(f"  [3] 避难所容量范围: [{int(cap.min())}, {int(cap.max())}]", end="")
    if int(cap.min()) >= 2000 and int(cap.max()) <= 10000:
        print("   PASS")
    else:
        print("   FAIL (需 2000~10000)"); ok = False

    # 4. 每类设施 >= 40
    print(f"  [4] 数量: 危险源 {len(hazards)}, 消防站 {len(rescue)}, 避难所 {len(shelters)}", end="")
    if len(hazards) >= 40 and len(rescue) >= 40 and len(shelters) >= 40:
        print("   PASS")
    else:
        print("   FAIL (每类需 >=40)"); ok = False

    print("=" * 60)
    print("验证结果:", "全部通过" if ok else "存在失败项")
    return ok


# ── 主流程 ───────────────────────────────────────────────
def main():
    print("=" * 60)
    print("step6b_improve_facilities — 设施数据分布合理性补强")
    print("=" * 60)

    districts = load_districts()
    print(f"已读取区县边界: {len(districts)} 个区县")
    print(f"  {list(districts['name'])}")

    hazards = process_hazards(districts)
    rescue = process_rescue(districts)
    shelters = process_shelters(districts)

    district_summary(hazards, rescue, shelters, districts)

    ok = validate(districts)
    if not ok:
        print("\n注意：验证未全部通过，请检查上述失败项。")
    print("\n=== step6b 完成 ===")


if __name__ == "__main__":
    main()
