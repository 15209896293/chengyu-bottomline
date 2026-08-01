"""
Step 1: 合肥市区县级行政区划数据加载与可视化
读取 DataV GeoJSON → 打印区县列表 → 转坐标系 → 保存 Folium 交互地图
"""
import os
from pathlib import Path

# ── 修复 Windows 下 GDAL/PROJ 数据路径 ──────────────────
LIB = Path("F:/anaconda/envs/zhenmai/Library/share")
os.environ.setdefault("GDAL_DATA", str(LIB / "gdal"))
os.environ.setdefault("PROJ_LIB", str(LIB / "proj"))

import warnings
warnings.filterwarnings("ignore")

import geopandas as gpd
import folium

# ── 路径配置 ────────────────────────────────────────────
DATA_DIR = Path(__file__).resolve().parent.parent / "数据文件"
GEOJSON_PATH = DATA_DIR / "hefei_districts.geojson"
OUTPUT_DIR = DATA_DIR

# ── 1. 读取数据 ─────────────────────────────────────────
gdf = gpd.read_file(GEOJSON_PATH)
print(f"坐标系: {gdf.crs}")
print(f"共 {len(gdf)} 个区县:\n")

for _, row in gdf.iterrows():
    name = row["name"]
    adcode = row["adcode"]
    c = row.geometry.centroid
    print(f"  {adcode}  {name}  中心点=({c.x:.4f}, {c.y:.4f})")

# ── 2. 转坐标系（CGCS2000，项目要求） ──────────────────
gdf_4490 = gdf.to_crs("EPSG:4490")
out_path = OUTPUT_DIR / "hefei_districts_4490.geojson"
gdf_4490.to_file(out_path, driver="GeoJSON")
print(f"\n已保存坐标系转换后数据 -> {out_path}")

# ── 3. Folium 交互地图 ─────────────────────────────────
# 计算合肥市中心点
center_lat = gdf.geometry.centroid.y.mean()
center_lon = gdf.geometry.centroid.x.mean()

m = folium.Map(location=[center_lat, center_lon], zoom_start=9, tiles="OpenStreetMap")

# 添加区县边界
folium.GeoJson(
    gdf.__geo_interface__,
    name="区县边界",
    style_function=lambda x: {
        "fillColor": "#3388ff",
        "color": "#333333",
        "weight": 1.5,
        "fillOpacity": 0.2,
    },
    tooltip=folium.GeoJsonTooltip(
        fields=["name", "adcode"],
        aliases=["名称:", "区划代码:"],
    ),
).add_to(m)

# 标注区县名
for _, row in gdf.iterrows():
    c = row.geometry.centroid
    folium.Marker(
        location=[c.y, c.x],
        icon=folium.DivIcon(
            html=f'<div style="font-size:11px;font-weight:bold;color:#333;'
                 f'text-shadow:0 0 3px #fff;white-space:nowrap">{row["name"]}</div>'
        ),
    ).add_to(m)

folium.LayerControl().add_to(m)

html_path = OUTPUT_DIR / "hefei_districts.html"
m.save(str(html_path))
print(f"\n交互地图已保存 -> {html_path}")
print("用浏览器打开该 HTML 文件即可查看")
