"""
多震级场景批量生成脚本
对 M5.0/5.5/6.0/6.5/7.0/7.5 生成各自的烈度、损失、路网阻断、可达性数据

输出结构:
  数据文件/
  ├── grid_base.geojson           # 静态网格（几何+区县+缓冲区+医院数+距离）
  ├── grid_intensity_M5.0.csv     # 每个震级的烈度/损失率
  ├── grid_intensity_M5.5.csv
  ├── ...
  ├── loss_estimate_M5.0.csv      # 每个震级的区县损失汇总
  ├── ...
  ├── road_blocked_M5.0.geojson   # 每个震级的路段阻断
  ├── ...
  ├── accessibility_M5.0.csv      # 每个震级的医院可达性
  └── ...
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
from shapely.geometry import Point, LineString, box
from shapely.ops import unary_union
from math import log, sin, cos, radians

# ── 配置 ────────────────────────────────────────────────
DATA_DIR = Path(__file__).resolve().parent.parent / "数据文件"
CRS_GEO = "EPSG:4490"
CRS_PROJ = "EPSG:4527"
GRID_SIZE = 500
MAGNITUDES = [5.0, 5.5, 6.0, 6.5, 7.0, 7.5]
SEED = 42

# 烈度衰减公式参数
ATTEN_ALPHA = 0.5
ATTEN_BETA = 1.5
ATTEN_GAMMA = 1.0
ATTEN_OFFSET = 5.0


def loss_rate(i):
    """烈度→损失率分档"""
    if i < 5:
        return 0.0
    elif i < 7:
        return 0.05
    elif i < 8:
        return 0.20
    else:
        return 0.50


# ── 1. 加载数据 ─────────────────────────────────────────
print("=" * 60)
print("加载基础数据...")
districts = gpd.read_file(DATA_DIR / "hefei_districts_4490.geojson")
fault = gpd.read_file(DATA_DIR / "tanlu_fault_hefei_4490.geojson")
hospitals = pd.read_csv(DATA_DIR / "hefei_hospital.csv")

districts_proj = districts.to_crs(CRS_PROJ)
fault_proj = fault.to_crs(CRS_PROJ)
hefei_boundary = unary_union(districts_proj.geometry)

# 震中
epicenter_proj = fault_proj.geometry.centroid.iloc[0]
epicenter_geo = fault.to_crs(CRS_GEO).geometry.centroid.iloc[0]
print(f"  震中: ({epicenter_geo.x:.4f}, {epicenter_geo.y:.4f})")

# ── 2. 生成静态网格（只跑一次） ──────────────────────────
print("\n生成500m静态网格（所有震级共用）...")
bounds = districts_proj.total_bounds
cols = int((bounds[2] - bounds[0]) / GRID_SIZE) + 1
rows = int((bounds[3] - bounds[1]) / GRID_SIZE) + 1

cells = []
for r in range(rows):
    y = bounds[1] + r * GRID_SIZE
    for c in range(cols):
        x = bounds[0] + c * GRID_SIZE
        cells.append(box(x, y, x + GRID_SIZE, y + GRID_SIZE))

grid = gpd.GeoDataFrame({"cell_id": range(len(cells))}, geometry=cells, crs=CRS_PROJ)
grid = grid[grid.intersects(hefei_boundary)].copy().reset_index(drop=True)
print(f"  网格数: {len(grid)}")

# 缓冲区（静态，不随震级变化）
fault_line_proj = fault_proj.geometry.iloc[0]
BUFFER_LEVELS = [10, 30, 50]
buffer_records = []
for d in BUFFER_LEVELS:
    buf_proj = fault_line_proj.buffer(d * 1000)
    buffer_records.append({"distance_km": d, "geometry": buf_proj})
buffers_proj = gpd.GeoDataFrame(buffer_records, crs=CRS_PROJ)

# 打标签：区县
print("  打标签: 区县归属...")
grid["district"] = ""
for i, row in districts_proj.iterrows():
    mask = grid.within(row.geometry)
    grid.loc[mask, "district"] = row["name"]
unassigned = grid["district"] == ""
if unassigned.any():
    for idx in grid[unassigned].index:
        pt = grid.at[idx, "geometry"].centroid
        dists = districts_proj.distance(pt)
        grid.at[idx, "district"] = districts_proj.loc[dists.idxmin(), "name"]

# 打标签：缓冲区
print("  打标签: 缓冲区级别...")
grid["buffer_km"] = 0
for _, buf_row in buffers_proj.iterrows():
    level = buf_row["distance_km"]
    mask = grid.intersects(buf_row.geometry)
    grid.loc[mask, "buffer_km"] = grid.loc[mask, "buffer_km"].clip(lower=level)

# 医院密度
print("  计算医院密度...")
hosp_gdf = gpd.GeoDataFrame(
    hospitals,
    geometry=gpd.points_from_xy(hospitals["lng"], hospitals["lat"]),
    crs="EPSG:4326",
).to_crs(CRS_PROJ)
grid["hospital_count"] = 0
hosp_joined = gpd.sjoin(hosp_gdf, grid[["geometry"]], how="inner", predicate="within")
counts = hosp_joined.groupby("index_right").size()
for idx, cnt in counts.items():
    grid.at[idx, "hospital_count"] = cnt

# 距离
grid["centroid"] = grid.geometry.centroid
grid["dist_to_epi_km"] = grid["centroid"].apply(
    lambda pt: pt.distance(epicenter_proj) / 1000.0
)

# 保存静态网格（不含centroid，转地理坐标）
grid_geo = grid.to_crs(CRS_GEO)
grid_geo = grid_geo.drop(columns=["centroid"])
grid_geo.to_file(DATA_DIR / "grid_base.geojson", driver="GeoJSON")
print(f"  静态网格已保存 -> grid_base.geojson ({len(grid_geo)} cells)")

# ── 3. 模拟路网（只跑一次，几何不变） ───────────────────
print("\n生成模拟路网...")
hefei_center = hefei_boundary.centroid
cx, cy = hefei_center.x, hefei_center.y
roads = []

for angle in range(0, 360, 15):
    rad = radians(angle)
    roads.append(LineString([(cx, cy), (cx + 50000 * cos(rad), cy + 50000 * sin(rad))]))

for r in [5000, 10000, 15000, 20000, 25000]:
    circle_pts = [(cx + r * cos(radians(a)), cy + r * sin(radians(a))) for a in range(0, 361, 10)]
    roads.append(LineString(circle_pts))

b50 = buffers_proj[buffers_proj["distance_km"] == 50].geometry.iloc[0]
clip_area = hefei_boundary.union(b50)

clipped = []
for r in roads:
    if r.intersects(clip_area):
        inter = r.intersection(clip_area)
        if inter.geom_type == "LineString":
            clipped.append(inter)
        elif inter.geom_type == "MultiLineString":
            clipped.extend(list(inter.geoms))

base_roads = gpd.GeoDataFrame(
    {"road_id": range(len(clipped))},
    geometry=clipped,
    crs=CRS_PROJ,
).reset_index(drop=True)
base_roads["road_id"] = base_roads.index
print(f"  路段数: {len(base_roads)}")

# ── 4. 按震级批量生成 ───────────────────────────────────
print("\n" + "=" * 60)
for MAG in MAGNITUDES:
    np.random.seed(SEED)  # 每个震级用相同种子保证可复现
    mag_str = f"M{MAG:.1f}"
    print(f"\n处理震级: {mag_str}")

    # ── 4a. 烈度衰减 ────────────────────────────────────
    grid_w = grid.copy()
    grid_w["intensity"] = (
        ATTEN_ALPHA + ATTEN_BETA * MAG - ATTEN_GAMMA * np.log(grid_w["dist_to_epi_km"] + ATTEN_OFFSET)
    )
    grid_w["intensity"] = grid_w["intensity"].clip(lower=0)
    grid_w["loss_rate"] = grid_w["intensity"].apply(loss_rate)
    grid_w["grid_loss"] = grid_w["hospital_count"] * grid_w["loss_rate"]

    # 保存烈度CSV（只保存必要列）
    intensity_df = grid_w[["cell_id", "intensity", "loss_rate", "grid_loss"]].copy()
    intensity_out = DATA_DIR / f"grid_intensity_{mag_str}.csv"
    intensity_df.to_csv(intensity_out, index=False, encoding="utf-8-sig")
    print(f"  -> grid_intensity_{mag_str}.csv ({len(intensity_df)} rows)")

    # ── 4b. 区县损失汇总 ──────────────────────────────────
    grid_w["affected"] = grid_w["buffer_km"] > 0
    summary = grid_w.groupby("district").agg(
        total_hospitals=("hospital_count", "sum"),
        affected_hospitals=("hospital_count", lambda x: (x * grid_w.loc[x.index, "affected"]).sum()),
        avg_intensity=("intensity", "mean"),
        total_grid_loss=("grid_loss", "sum"),
    ).reset_index()
    summary["loss_rate_pct"] = (
        summary["total_grid_loss"] / summary["total_hospitals"].replace(0, 1) * 100
    ).round(1)
    summary["estimated_loss"] = summary["total_grid_loss"].round(2)
    summary["total_hospitals"] = summary["total_hospitals"].astype(int)
    summary["affected_hospitals"] = summary["affected_hospitals"].astype(int)
    summary["avg_intensity"] = summary["avg_intensity"].round(2)

    loss_out = summary[["district", "total_hospitals", "affected_hospitals",
                         "avg_intensity", "loss_rate_pct", "estimated_loss"]]
    loss_out.to_csv(DATA_DIR / f"loss_estimate_{mag_str}.csv", index=False, encoding="utf-8-sig")
    print(f"  -> loss_estimate_{mag_str}.csv")

    # ── 4c. 路网阻断 ─────────────────────────────────────
    # Rupture zone: cubic growth with magnitude (M5.0=50m, M6.0=113m, M7.0=229m, M7.5=300m)
    rupture_width = 50 + 250 * ((MAG - 5.0) / 2.5) ** 1.5
    rupture_zone = fault_proj.geometry.iloc[0].buffer(rupture_width)

    buf_10km = buffers_proj[buffers_proj["distance_km"] == 10].geometry.iloc[0]
    buf_30km = buffers_proj[buffers_proj["distance_km"] == 30].geometry.iloc[0]
    buf_50km = buffers_proj[buffers_proj["distance_km"] == 50].geometry.iloc[0]

    # Blocking probability: power-law scaling for dramatic M5→M7 difference
    # 30km ring: M5.0≈0.5%, M6.0≈12.5%, M7.0≈58%, M7.5≈92%
    prob_30km = min(((MAG - 4.5) / 3.0) ** 3, 0.92)
    # 50km ring: M5.0≈0.1%, M6.0≈8%, M7.0≈46%, M7.5≈65%
    prob_50km = min(((MAG - 4.8) / 3.0) ** 2.5, 0.65)

    # 10km zone: magnitude-dependent to create visible M5→M7 contrast
    p_full_10km = min(((MAG - 4.5) / 3.0) ** 2.5, 0.95)
    p_severe_10km = min(((MAG - 4.3) / 3.5) ** 2.5, 0.90)

    def classify_road(geom):
        if geom.intersects(rupture_zone):
            return "完全阻断"
        mid = geom.centroid if geom.geom_type == "LineString" else geom.centroid
        if buf_10km.contains(mid):
            r = np.random.random()
            if r < p_full_10km:
                return "完全阻断"
            elif r < p_full_10km + p_severe_10km * (1 - p_full_10km):
                return "严重损伤"
            else:
                return "正常"
        elif buf_30km.contains(mid):
            return "严重损伤" if np.random.random() < prob_30km else "正常"
        elif buf_50km.contains(mid):
            return "轻度损伤" if np.random.random() < prob_50km else "正常"
        else:
            return "正常"

    roads_w = base_roads.copy()
    roads_w["block_level"] = roads_w.geometry.apply(classify_road)
    road_geo = roads_w.to_crs(CRS_GEO)
    road_geo.to_file(DATA_DIR / f"road_blocked_{mag_str}.geojson", driver="GeoJSON")
    print(f"  -> road_blocked_{mag_str}.geojson")

    # ── 4d. 医院可达性 ────────────────────────────────────
    blocked_roads = roads_w[roads_w["block_level"] != "正常"]
    fully_blocked = roads_w[roads_w["block_level"] == "完全阻断"]
    severe_roads = roads_w[roads_w["block_level"] == "严重损伤"]

    access_records = []
    for _, hosp in hosp_gdf.iterrows():
        hpt = hosp.geometry
        buf_1km = hpt.buffer(1000)
        has_full = any(fully_blocked.intersects(buf_1km))
        has_severe = any(severe_roads.intersects(buf_1km))

        if has_full:
            acc = "不可达"
        elif has_severe:
            acc = "可达但受限"
        else:
            acc = "正常可达"

        dist_to_fault = hpt.distance(fault_proj.geometry.iloc[0]) / 1000
        if dist_to_fault <= 10:
            hb = 10
        elif dist_to_fault <= 30:
            hb = 30
        elif dist_to_fault <= 50:
            hb = 50
        else:
            hb = 0

        for _, drow in districts_proj.iterrows():
            if hpt.within(drow.geometry):
                district = drow["name"]
                break
        else:
            district = "未知"

        access_records.append({
            "name": hosp["name"], "lng": hosp["lng"], "lat": hosp["lat"],
            "type": hosp.get("type", ""), "district": district,
            "dist_to_fault_km": round(dist_to_fault, 1),
            "buffer_km": hb, "accessibility": acc,
        })

    acc_df = pd.DataFrame(access_records)
    acc_df.to_csv(DATA_DIR / f"accessibility_{mag_str}.csv", index=False, encoding="utf-8-sig")

    # 快速统计
    acc_counts = acc_df["accessibility"].value_counts()
    road_counts = roads_w["block_level"].value_counts()
    print(f"  可达性: 不可达={acc_counts.get('不可达',0)}, "
          f"正常={acc_counts.get('正常可达',0)}")
    print(f"  阻断: 完全阻断={road_counts.get('完全阻断',0)}, "
          f"严重损伤={road_counts.get('严重损伤',0)}, 正常={road_counts.get('正常',0)}")

print("\n" + "=" * 60)
print("全部震级场景生成完成！")
print(f"输出目录: {DATA_DIR}")
