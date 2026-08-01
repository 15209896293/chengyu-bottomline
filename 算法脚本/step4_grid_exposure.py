"""
模块1A：500m网格化暴露度与地震损失初估
输入: 区县边界 + 断裂带 + 缓冲区 + 医院POI
输出: grid_exposure.geojson + loss_estimate.csv
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
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union
from math import log

# ── 配置 ────────────────────────────────────────────────
DATA_DIR = Path(__file__).resolve().parent.parent / "数据文件"
CRS_GEO = "EPSG:4490"       # CGCS2000 地理坐标
CRS_PROJ = "EPSG:4527"      # CGCS2000 投影坐标(3度带39, 合肥所在)
GRID_SIZE = 500              # 网格边长(m)
MAGNITUDE = 6.0              # 假设震级
ATTEN_ALPHA = 0.5            # 衰减公式常数
ATTEN_BETA = 1.5             # 衰减公式震级系数
ATTEN_GAMMA = 1.0            # 衰减公式距离系数
ATTEN_OFFSET = 5.0           # 衰减公式距离偏移(km)

# ── 1. 加载数据 ─────────────────────────────────────────
print("加载数据...")
districts = gpd.read_file(DATA_DIR / "hefei_districts_4490.geojson")
fault = gpd.read_file(DATA_DIR / "tanlu_fault_hefei_4490.geojson")
hospitals = pd.read_csv(DATA_DIR / "hefei_hospital.csv")

# 转投影坐标系做距离计算
districts_proj = districts.to_crs(CRS_PROJ)
fault_proj = fault.to_crs(CRS_PROJ)

# ⚠️ Step2的buffer是在EPSG:4490(度)里算的，完全错误。这里用投影坐标系重算。
fault_line_proj = fault_proj.geometry.iloc[0]
BUFFER_LEVELS = [10, 30, 50]  # km
buffer_records = []
for d in BUFFER_LEVELS:
    buf_proj = fault_line_proj.buffer(d * 1000)  # 投影坐标系下单位是米
    buffer_records.append({"distance_km": d, "geometry": buf_proj})
buffers_proj = gpd.GeoDataFrame(buffer_records, crs=CRS_PROJ)
# 重新保存正确的buffer
buffers_geo = buffers_proj.to_crs(CRS_GEO)
buffers_geo.to_file(DATA_DIR / "tanlu_buffer_4490.geojson", driver="GeoJSON")
print(f"  已修正缓冲区 -> {DATA_DIR / 'tanlu_buffer_4490.geojson'}")

# 医院 → Point GeoDataFrame
hosp_gdf = gpd.GeoDataFrame(
    hospitals,
    geometry=gpd.points_from_xy(hospitals["lng"], hospitals["lat"]),
    crs="EPSG:4326",
).to_crs(CRS_PROJ)

print(f"  区县: {len(districts)}, 医院: {len(hospitals)}, 缓冲区级别: {BUFFER_LEVELS}")

# ── 2. 生成500m网格 ────────────────────────────────────
print("生成500m网格...")
bounds = districts_proj.total_bounds  # [minx, miny, maxx, maxy]
cols = int((bounds[2] - bounds[0]) / GRID_SIZE) + 1
rows = int((bounds[3] - bounds[1]) / GRID_SIZE) + 1

cells = []
for r in range(rows):
    y = bounds[1] + r * GRID_SIZE
    for c in range(cols):
        x = bounds[0] + c * GRID_SIZE
        cells.append(box(x, y, x + GRID_SIZE, y + GRID_SIZE))

grid = gpd.GeoDataFrame({"cell_id": range(len(cells))}, geometry=cells, crs=CRS_PROJ)
print(f"  总网格数: {len(grid)}")

# ── 2a. 裁剪到合肥市边界 ────────────────────────────────
hefei_union = unary_union(districts_proj.geometry)
grid = grid[grid.intersects(hefei_union)].copy()
grid = grid.reset_index(drop=True)
print(f"  裁剪后: {len(grid)}")

# ── 2b. 打标签：所属区县 ────────────────────────────────
print("打标签: 区县归属、缓冲区级别...")
grid["district"] = ""
grid["buffer_km"] = 0  # 0=不在缓冲区内

for i, row in districts_proj.iterrows():
    mask = grid.within(row.geometry)
    grid.loc[mask, "district"] = row["name"]

# 不在任何区县内的网格取最近区县
unassigned = grid["district"] == ""
if unassigned.any():
    for idx in grid[unassigned].index:
        pt = grid.at[idx, "geometry"].centroid
        dists = districts_proj.distance(pt)
        grid.at[idx, "district"] = districts_proj.loc[dists.idxmin(), "name"]

# ── 2c. 打标签：缓冲区级别 ──────────────────────────────
for _, buf_row in buffers_proj.iterrows():
    level = buf_row["distance_km"]
    mask = grid.intersects(buf_row.geometry)
    # 取最大级别（50km > 30km > 10km）
    grid.loc[mask, "buffer_km"] = grid.loc[mask, "buffer_km"].clip(lower=level)

# ── 2d. 计算每个网格的医院数量 ──────────────────────────
print("计算医院密度...")
grid["hospital_count"] = 0
hosp_joined = gpd.sjoin(hosp_gdf, grid[["geometry"]], how="inner", predicate="within")
counts = hosp_joined.groupby("index_right").size()
for idx, cnt in counts.items():
    grid.at[idx, "hospital_count"] = cnt

# ── 3. 地震损失模型 ────────────────────────────────────
print("计算地震损失...")

# 震中：断裂带中点
epicenter_proj = fault_proj.geometry.centroid.iloc[0]
epicenter_geo = fault.to_crs(CRS_GEO).geometry.centroid.iloc[0]
print(f"  震中(假设): ({epicenter_geo.x:.4f}, {epicenter_geo.y:.4f})")

# 每个网格到震中距离(km)
grid["centroid"] = grid.geometry.centroid
grid["dist_to_epi_km"] = grid["centroid"].apply(
    lambda pt: pt.distance(epicenter_proj) / 1000.0
)

# 衰减公式: I = 0.5 + 1.5*M - 1.0*ln(R+5)
grid["intensity"] = ATTEN_ALPHA + ATTEN_BETA * MAGNITUDE - ATTEN_GAMMA * np.log(grid["dist_to_epi_km"] + ATTEN_OFFSET)
grid["intensity"] = grid["intensity"].clip(lower=0)  # 烈度不能为负

# 损失率
def loss_rate(i):
    if i < 5:
        return 0.0
    elif i < 7:
        return 0.05
    elif i < 8:
        return 0.20
    else:
        return 0.50

grid["loss_rate"] = grid["intensity"].apply(loss_rate)
# 网格级医院功能损失
grid["grid_loss"] = grid["hospital_count"] * grid["loss_rate"]

# ── 4. 转回地理坐标系并保存网格 ─────────────────────────
grid_geo = grid.to_crs(CRS_GEO)
grid_geo = grid_geo.drop(columns=["centroid"])
grid_geo.to_file(DATA_DIR / "grid_exposure.geojson", driver="GeoJSON")
print(f"网格已保存 -> {DATA_DIR / 'grid_exposure.geojson'}")

# ── 5. 按区县汇总 ───────────────────────────────────────
print("按区县汇总损失...")

# 受影响医院数：在50km缓冲区内的医院
grid["affected"] = grid["buffer_km"] > 0

summary = grid.groupby("district").agg(
    grid_count=("cell_id", "count"),
    total_hospitals=("hospital_count", "sum"),
    affected_hospitals=("hospital_count", lambda x: (x * grid.loc[x.index, "affected"]).sum()),
    avg_intensity=("intensity", "mean"),
    max_intensity=("intensity", "max"),
    total_grid_loss=("grid_loss", "sum"),
).reset_index()

summary["loss_rate_pct"] = (summary["total_grid_loss"] / summary["total_hospitals"].replace(0, 1) * 100).round(1)
summary["estimated_loss"] = summary["total_grid_loss"].round(2)

# 整理输出列
out_cols = ["district", "total_hospitals", "affected_hospitals",
            "avg_intensity", "loss_rate_pct", "estimated_loss"]
loss_df = summary[out_cols].copy()
loss_df["avg_intensity"] = loss_df["avg_intensity"].round(2)
loss_df["total_hospitals"] = loss_df["total_hospitals"].astype(int)
loss_df["affected_hospitals"] = loss_df["affected_hospitals"].astype(int)

loss_df.to_csv(DATA_DIR / "loss_estimate.csv", index=False, encoding="utf-8-sig")
print(f"损失汇总已保存 -> {DATA_DIR / 'loss_estimate.csv'}")
print(f"\n{loss_df.to_string(index=False)}")


# ── 6. 自检验收 ─────────────────────────────────────────
def self_test():
    print("\n=== 模块1A 自检验收 ===")
    grid = gpd.read_file(DATA_DIR / "grid_exposure.geojson")
    loss = pd.read_csv(DATA_DIR / "loss_estimate.csv")
    print(f"网格总数: {len(grid)}")
    print(f"区县汇总:\n{loss.to_string()}")
    assert len(grid) > 1000, f"500m网格应该有上千个，实际{len(grid)}"
    assert "buffer_km" in grid.columns, "网格缺少buffer_km字段"
    assert len(loss) >= 4, f"合肥至少4个区县有数据，实际{len(loss)}"
    assert loss["avg_intensity"].between(0, 10).all(), "烈度值异常"
    print("[OK] 模块1A验收通过")

self_test()
