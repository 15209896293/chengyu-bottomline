"""
Step 2: 郯庐断裂带合肥段提取 + 多级缓冲区 + 叠加可视化
数据来源：CAFD2023 中国活动断层数据库（CN-faults）
"""
import os
from pathlib import Path

# ── 修复 Windows 下 GDAL/PROJ 数据路径 ──────────────────
LIB = Path("F:/anaconda/envs/zhenmai/Library/share")
os.environ.setdefault("GDAL_DATA", str(LIB / "gdal"))
os.environ.setdefault("PROJ_LIB", str(LIB / "proj"))

import warnings
warnings.filterwarnings("ignore")

import fiona
import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union
import folium
from branca.element import Template, MacroElement

# ── 路径配置 ────────────────────────────────────────────
DATA_DIR = Path(__file__).resolve().parent.parent / "数据文件"
RAW = DATA_DIR
PROCESSED = DATA_DIR
PROCESSED.mkdir(parents=True, exist_ok=True)

HEFEI_BBOX = (116.0, 30.5, 118.5, 33.0)  # 合肥周边范围

# ── 1. 从 CN-faults 提取合肥附近的郯庐断裂段 ──────────
print("正在读取 CN-faults.gmt...")
segments_in_bbox = []

with fiona.open(RAW / "CN-faults.gmt") as src:
    for feat in src:
        coords = feat["geometry"]["coordinates"]
        if not coords:
            continue
        lons = [c[0] for c in coords]
        lats = [c[1] for c in coords]
        min_lon, max_lon = min(lons), max(lons)
        min_lat, max_lat = min(lats), max(lats)
        # 检查是否与合肥范围相交
        if max_lon >= HEFEI_BBOX[0] and min_lon <= HEFEI_BBOX[2] and \
           max_lat >= HEFEI_BBOX[1] and min_lat <= HEFEI_BBOX[3]:
            segments_in_bbox.append(LineString([(c[0], c[1]) for c in coords]))

print(f"在合肥范围内找到 {len(segments_in_bbox)} 个断裂段")

# ── 2. 合并所有段为 GeoDataFrame，转 EPSG:4490 ──────────
tanlu_gdf = gpd.GeoDataFrame(
    {"name": ["郯庐断裂带（合肥段）"]},
    geometry=[unary_union(segments_in_bbox)],
    crs="EPSG:4326",
)
tanlu_gdf = tanlu_gdf.to_crs("EPSG:4490")
tanlu_path = PROCESSED / "tanlu_fault_hefei_4490.geojson"
tanlu_gdf.to_file(tanlu_path, driver="GeoJSON")
print(f"断裂带已保存 -> {tanlu_path}")

# ── 3. 生成三级缓冲区 ──────────────────────────────────
buffer_distances = {
    "10km": 10000,
    "30km": 30000,
    "50km": 50000,
}

buffer_records = []
for label, dist in buffer_distances.items():
    buf = tanlu_gdf.geometry.buffer(dist).iloc[0]
    buffer_records.append({"level": label, "distance_km": int(label[:-2]), "geometry": buf})

buffer_gdf = gpd.GeoDataFrame(buffer_records, crs="EPSG:4490")
buffer_path = PROCESSED / "tanlu_buffer_4490.geojson"
buffer_gdf.to_file(buffer_path, driver="GeoJSON")
print(f"缓冲区已保存 -> {buffer_path}")
for _, row in buffer_gdf.iterrows():
    area_km2 = row.geometry.area / 1e6
    print(f"  {row['level']} 缓冲区面积: {area_km2:.0f} km2")

# ── 4. 加载合肥市行政区划 ───────────────────────────────
hefei_gdf = gpd.read_file(RAW / "hefei_districts.geojson")
hefei_gdf = hefei_gdf.to_crs("EPSG:4490")

# ── 5. Folium 叠加可视化 ────────────────────────────────
center = hefei_gdf.to_crs("EPSG:4326").geometry.centroid
m = folium.Map(location=[center.y.mean(), center.x.mean()], zoom_start=9, tiles="OpenStreetMap")

# 5.1 缓冲区（底层，浅色填充）
buffer_colors = {"10km": "#ff6600", "30km": "#ff9900", "50km": "#ffcc00"}
for _, row in buffer_gdf.to_crs("EPSG:4326").iterrows():
    folium.GeoJson(
        row.geometry.__geo_interface__,
        name=f"缓冲区 {row['level']}",
        style_function=lambda x, c=row['level']: {
            "fillColor": buffer_colors[c],
            "color": buffer_colors[c],
            "weight": 1,
            "fillOpacity": 0.15,
        },
    ).add_to(m)

# 5.2 断裂带线
folium.GeoJson(
    tanlu_gdf.to_crs("EPSG:4326").__geo_interface__,
    name="郯庐断裂带",
    style_function=lambda x: {"color": "#cc0000", "weight": 2.5},
    tooltip="郯庐断裂带（合肥段）",
).add_to(m)

# 5.3 合肥市区县
folium.GeoJson(
    hefei_gdf.to_crs("EPSG:4326").__geo_interface__,
    name="合肥市区县",
    style_function=lambda x: {"fillColor": "#3388ff", "color": "#333", "weight": 1.5, "fillOpacity": 0.1},
    tooltip=folium.GeoJsonTooltip(fields=["name"], aliases=["区县:"]),
).add_to(m)

# 5.4 标注区县名
for _, row in hefei_gdf.to_crs("EPSG:4326").iterrows():
    c = row.geometry.centroid
    folium.Marker(
        location=[c.y, c.x],
        icon=folium.DivIcon(
            html=f'<div style="font-size:10px;font-weight:bold;color:#333;'
                 f'text-shadow:0 0 3px #fff;white-space:nowrap">{row["name"]}</div>'
        ),
    ).add_to(m)

folium.LayerControl().add_to(m)

map_path = PROCESSED / "tanlu_hefei_overlay.html"
m.save(str(map_path))
print(f"\n叠加地图已保存 -> {map_path}")
print("用浏览器打开即可查看：断裂带 + 缓冲区 + 合肥区县")
