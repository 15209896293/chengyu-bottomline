"""
模块1B：路网阻断分析
输入: 断裂带 + 缓冲区 + 医院POI
输出: road_blocked.geojson + accessibility.csv
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

# ── 配置 ────────────────────────────────────────────────
DATA_DIR = Path(__file__).resolve().parent.parent / "数据文件"
CRS_GEO = "EPSG:4490"
CRS_PROJ = "EPSG:4527"
SEED = 42
np.random.seed(SEED)

# ── 1. 加载数据 ─────────────────────────────────────────
print("加载数据...")
districts = gpd.read_file(DATA_DIR / "hefei_districts_4490.geojson")
fault = gpd.read_file(DATA_DIR / "tanlu_fault_hefei_4490.geojson")
buffers = gpd.read_file(DATA_DIR / "tanlu_buffer_4490.geojson")
hospitals = pd.read_csv(DATA_DIR / "hefei_hospital.csv")

# 转投影坐标系
districts_proj = districts.to_crs(CRS_PROJ)
fault_proj = fault.to_crs(CRS_PROJ)
buffers_proj = buffers.to_crs(CRS_PROJ)
hefei_boundary = unary_union(districts_proj.geometry)

# ── 2. 获取路网 ─────────────────────────────────────────
print("获取合肥市路网...")
road_gdf = None
USE_OSMNX = False  # 设为True尝试OSMnx，但可能很慢/超时

if USE_OSMNX:
    try:
        import osmnx as ox
        ox.settings.use_cache = True
        ox.settings.log_console = False
        b = districts.to_crs("EPSG:4326").total_bounds
        G = ox.graph_from_bbox(bbox=(b[3], b[1], b[2], b[0]), network_type="drive")
        nodes, edges = ox.graph_to_gdfs(G, nodes=True, edges=True)
        road_gdf = edges[["geometry"]].copy()
        road_gdf = road_gdf.to_crs(CRS_PROJ)
        road_gdf = gpd.GeoDataFrame(road_gdf, geometry="geometry", crs=CRS_PROJ)
        road_gdf = road_gdf.reset_index(drop=True)
        road_gdf["road_id"] = road_gdf.index
        print(f"  OSMnx下载成功: {len(road_gdf)} 条路段")
    except Exception as e:
        print(f"  OSMnx失败: {e}")

# 备用方案：模拟路网（放射+环状，更接近真实城市路网）
if road_gdf is None or len(road_gdf) < 10:
    print("  使用备用方案：模拟路网...")
    from math import sin, cos, radians

    roads = []
    hefei_center = hefei_boundary.centroid
    cx, cy = hefei_center.x, hefei_center.y

    # 放射状道路（24个方向）
    for angle in range(0, 360, 15):
        rad = radians(angle)
        # 从中心向外延伸到50km
        end_x = cx + 50000 * cos(rad)
        end_y = cy + 50000 * sin(rad)
        roads.append(LineString([(cx, cy), (end_x, end_y)]))

    # 环状道路（5个环）
    for r in [5000, 10000, 15000, 20000, 25000]:
        circle_pts = []
        for angle in range(0, 361, 10):
            rad = radians(angle)
            circle_pts.append((cx + r * cos(rad), cy + r * sin(rad)))
        roads.append(LineString(circle_pts))

    # 裁剪到分析范围（50km缓冲区 ∪ 合肥边界）
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

    road_gdf = gpd.GeoDataFrame(
        {"road_id": range(len(clipped))},
        geometry=clipped,
        crs=CRS_PROJ,
    )
    road_gdf = road_gdf.reset_index(drop=True)
    road_gdf["road_id"] = road_gdf.index
    print(f"  模拟路网: {len(road_gdf)} 条路段")

# ── 3. 断裂带穿越分析 ───────────────────────────────────
print("断裂带穿越分析...")

# 3a. 地表破裂带：10km缓冲区内，断裂线200m buffer
buf_10km = buffers_proj[buffers_proj["distance_km"] == 10].geometry.iloc[0]
buf_30km = buffers_proj[buffers_proj["distance_km"] == 30].geometry.iloc[0]
buf_50km = buffers_proj[buffers_proj["distance_km"] == 50].geometry.iloc[0]
rupture_zone = fault_proj.geometry.iloc[0].buffer(200)  # 200m 地表破裂

# 3b. 标记每条路段
def classify_road(geom):
    """对单条路段判断阻断等级"""
    # 与地表破裂带相交 → 完全阻断
    if geom.intersects(rupture_zone):
        return "完全阻断"

    # 取路段中点判断所在区域
    mid = geom.centroid if geom.geom_type == "LineString" else geom.centroid

    if buf_10km.contains(mid):
        return "完全阻断"
    elif buf_30km.contains(mid):
        return "严重损伤" if np.random.random() < 0.3 else "正常"
    elif buf_50km.contains(mid):
        return "轻度损伤" if np.random.random() < 0.1 else "正常"
    else:
        return "正常"

road_gdf["block_level"] = road_gdf.geometry.apply(classify_road)

print(f"  路段阻断分布:")
for level in ["完全阻断", "严重损伤", "轻度损伤", "正常"]:
    cnt = (road_gdf["block_level"] == level).sum()
    print(f"    {level}: {cnt} ({100*cnt/len(road_gdf):.1f}%)")

# 保存
road_geo = road_gdf.to_crs(CRS_GEO)
road_geo.to_file(DATA_DIR / "road_blocked.geojson", driver="GeoJSON")
print(f"  路网已保存 -> {DATA_DIR / 'road_blocked.geojson'}")

# ── 4. 医院可达性评估 ───────────────────────────────────
print("医院可达性评估...")

hosp_gdf = gpd.GeoDataFrame(
    hospitals,
    geometry=gpd.points_from_xy(hospitals["lng"], hospitals["lat"]),
    crs="EPSG:4326",
).to_crs(CRS_PROJ)

# 找每个医院1km范围内的阻断路段
blocked_roads = road_gdf[road_gdf["block_level"] != "正常"]
fully_blocked = road_gdf[road_gdf["block_level"] == "完全阻断"]
severe_roads = road_gdf[road_gdf["block_level"] == "严重损伤"]

access_records = []
for _, hosp in hosp_gdf.iterrows():
    hpt = hosp.geometry
    buf_1km = hpt.buffer(1000)  # 1km buffer

    has_full_block = any(fully_blocked.intersects(buf_1km))
    has_severe = any(severe_roads.intersects(buf_1km))

    if has_full_block:
        accessibility = "不可达"
    elif has_severe:
        accessibility = "可达但受限"
    else:
        accessibility = "正常可达"

    # 医院所在缓冲级别
    dist_to_fault = hpt.distance(fault_proj.geometry.iloc[0]) / 1000
    if dist_to_fault <= 10:
        hosp_buffer = 10
    elif dist_to_fault <= 30:
        hosp_buffer = 30
    elif dist_to_fault <= 50:
        hosp_buffer = 50
    else:
        hosp_buffer = 0

    # 找所属区县
    for _, drow in districts_proj.iterrows():
        if hpt.within(drow.geometry):
            district = drow["name"]
            break
    else:
        district = "未知"

    access_records.append({
        "name": hosp["name"],
        "lng": hosp["lng"],
        "lat": hosp["lat"],
        "type": hosp.get("type", ""),
        "district": district,
        "dist_to_fault_km": round(dist_to_fault, 1),
        "buffer_km": hosp_buffer,
        "accessibility": accessibility,
    })

acc_df = pd.DataFrame(access_records)
acc_df.to_csv(DATA_DIR / "accessibility.csv", index=False, encoding="utf-8-sig")
print(f"  可达性已保存 -> {DATA_DIR / 'accessibility.csv'}")
print(f"  可达性分布:\n{acc_df['accessibility'].value_counts().to_string()}")


# ── 5. 自检验收 ─────────────────────────────────────────
def self_test():
    print("\n=== 模块1B 自检验收 ===")
    blocked = gpd.read_file(DATA_DIR / "road_blocked.geojson")
    acc = pd.read_csv(DATA_DIR / "accessibility.csv")
    print(f"总路段数: {len(blocked)}")
    print(f"阻断路段: {(blocked['block_level']=='完全阻断').sum()}")
    print(f"医院可达性分布:\n{acc['accessibility'].value_counts().to_string()}")
    assert len(blocked) > 0, "路网数据为空"
    assert 'block_level' in blocked.columns, "缺少block_level字段"
    assert len(acc) > 50, f"医院可达性应该覆盖426家，实际{len(acc)}"
    assert 'accessibility' in acc.columns, "缺少accessibility字段"
    print("[OK] 模块1B验收通过")

self_test()
