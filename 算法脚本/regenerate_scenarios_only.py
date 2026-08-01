"""
Regenerate only the magnitude-dependent scenario files (skip static grid).
Uses the new power-law blocking probability scaling for dramatic M5→M7 difference.
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
from shapely.geometry import LineString, box
from shapely.ops import unary_union
from math import sin, cos, radians

DATA_DIR = Path(__file__).resolve().parent.parent / "数据文件"
CRS_GEO = "EPSG:4490"
CRS_PROJ = "EPSG:4527"
GRID_SIZE = 500
MAGNITUDES = [5.0, 5.5, 6.0, 6.5, 7.0, 7.5]
SEED = 42
ATTEN_ALPHA = 0.5; ATTEN_BETA = 1.5; ATTEN_GAMMA = 1.0; ATTEN_OFFSET = 5.0

def loss_rate(i):
    if i < 5: return 0.0
    elif i < 7: return 0.05
    elif i < 8: return 0.20
    else: return 0.50

print("Loading base data...")
districts = gpd.read_file(DATA_DIR / "hefei_districts_4490.geojson")
fault = gpd.read_file(DATA_DIR / "tanlu_fault_hefei_4490.geojson")
hospitals = pd.read_csv(DATA_DIR / "hefei_hospital.csv")
grid_base = gpd.read_file(DATA_DIR / "grid_base.geojson")

districts_proj = districts.to_crs(CRS_PROJ)
fault_proj = fault.to_crs(CRS_PROJ)
hefei_boundary = unary_union(districts_proj.geometry)

# Buffers
fault_line_proj = fault_proj.geometry.iloc[0]
BUFFER_LEVELS = [10, 30, 50]
buffer_records = []
for d in BUFFER_LEVELS:
    buf_proj = fault_line_proj.buffer(d * 1000)
    buffer_records.append({"distance_km": d, "geometry": buf_proj})
buffers_proj = gpd.GeoDataFrame(buffer_records, crs=CRS_PROJ)

# Grid in projected CRS
grid = grid_base.to_crs(CRS_PROJ)
grid["centroid"] = grid.geometry.centroid

epicenter_proj = fault_proj.geometry.centroid.iloc[0]
grid["dist_to_epi_km"] = grid["centroid"].apply(lambda pt: pt.distance(epicenter_proj) / 1000.0)

# Hospitals
hosp_gdf = gpd.GeoDataFrame(
    hospitals,
    geometry=gpd.points_from_xy(hospitals["lng"], hospitals["lat"]),
    crs="EPSG:4326",
).to_crs(CRS_PROJ)

# Simulated road network
print("Generating road network...")
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
print(f"  Road segments: {len(base_roads)}")

# ═══════════════════════════════════════════════════════
# Per-magnitude generation with NEW sensitivity scaling
# ═══════════════════════════════════════════════════════
print("\n" + "=" * 60)
for MAG in MAGNITUDES:
    np.random.seed(SEED)
    mag_str = f"M{MAG:.1f}"
    print(f"\nProcessing: {mag_str}")

    # Intensity
    grid_w = grid.copy()
    grid_w["intensity"] = (
        ATTEN_ALPHA + ATTEN_BETA * MAG - ATTEN_GAMMA * np.log(grid_w["dist_to_epi_km"] + ATTEN_OFFSET)
    )
    grid_w["intensity"] = grid_w["intensity"].clip(lower=0)
    grid_w["loss_rate"] = grid_w["intensity"].apply(loss_rate)
    grid_w["grid_loss"] = grid_w["hospital_count"] * grid_w["loss_rate"]

    intensity_df = grid_w[["cell_id", "intensity", "loss_rate", "grid_loss"]].copy()
    intensity_df.to_csv(DATA_DIR / f"grid_intensity_{mag_str}.csv", index=False, encoding="utf-8-sig")
    print(f"  -> grid_intensity_{mag_str}.csv")

    # Loss estimate
    grid_w["affected"] = grid_w["buffer_km"] > 0
    summary = grid_w.groupby("district").agg(
        total_hospitals=("hospital_count", "sum"),
        affected_hospitals=("hospital_count", lambda x: (x * grid_w.loc[x.index, "affected"]).sum()),
        avg_intensity=("intensity", "mean"),
        total_grid_loss=("grid_loss", "sum"),
    ).reset_index()
    summary["loss_rate_pct"] = (summary["total_grid_loss"] / summary["total_hospitals"].replace(0, 1) * 100).round(1)
    summary["estimated_loss"] = summary["total_grid_loss"].round(2)
    summary["total_hospitals"] = summary["total_hospitals"].astype(int)
    summary["affected_hospitals"] = summary["affected_hospitals"].astype(int)
    summary["avg_intensity"] = summary["avg_intensity"].round(2)
    loss_out = summary[["district", "total_hospitals", "affected_hospitals",
                         "avg_intensity", "loss_rate_pct", "estimated_loss"]]
    loss_out.to_csv(DATA_DIR / f"loss_estimate_{mag_str}.csv", index=False, encoding="utf-8-sig")
    print(f"  -> loss_estimate_{mag_str}.csv")

    # ── Road blocking with NEW sensitivity ──
    rupture_width = 50 + 250 * ((MAG - 5.0) / 2.5) ** 1.5
    rupture_zone = fault_proj.geometry.iloc[0].buffer(rupture_width)

    buf_10km = buffers_proj[buffers_proj["distance_km"] == 10].geometry.iloc[0]
    buf_30km = buffers_proj[buffers_proj["distance_km"] == 30].geometry.iloc[0]
    buf_50km = buffers_proj[buffers_proj["distance_km"] == 50].geometry.iloc[0]

    # Power-law probability for 30km/50km rings
    prob_30km = min(((MAG - 4.5) / 3.0) ** 3, 0.92)
    prob_50km = min(((MAG - 4.8) / 3.0) ** 2.5, 0.65)

    # 10km zone: also magnitude-dependent to create visible M5→M7 contrast
    # M5.0: ~3% blocked, M6.0: ~37%, M7.0: ~81%, M7.5: ~95%
    p_full_10km = min(((MAG - 4.5) / 3.0) ** 2.5, 0.95)
    p_severe_10km = min(((MAG - 4.3) / 3.5) ** 2.5, 0.90)

    print(f"  Rupture: {rupture_width:.0f}m, P10km_full: {p_full_10km:.1%}, "
          f"P10km_severe: {p_severe_10km:.1%}, P30km: {prob_30km:.1%}, P50km: {prob_50km:.1%}")

    def classify_road(geom):
        # Rupture zone: always fully blocked
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

    # Accessibility
    blocked_roads = roads_w[roads_w["block_level"] != "正常"]
    fully_blocked = roads_w[roads_w["block_level"] == "完全阻断"]
    severe_roads = roads_w[roads_w["block_level"] == "严重损伤"]

    access_records = []
    for _, hosp in hosp_gdf.iterrows():
        hpt = hosp.geometry
        buf_1km = hpt.buffer(1000)
        has_full = any(fully_blocked.intersects(buf_1km))
        has_severe = any(severe_roads.intersects(buf_1km))
        if has_full: acc = "不可达"
        elif has_severe: acc = "可达但受限"
        else: acc = "正常可达"

        dist_to_fault = hpt.distance(fault_proj.geometry.iloc[0]) / 1000
        hb = 10 if dist_to_fault <= 10 else (30 if dist_to_fault <= 30 else (50 if dist_to_fault <= 50 else 0))

        for _, drow in districts_proj.iterrows():
            if hpt.within(drow.geometry): district = drow["name"]; break
        else: district = "Unknown"

        access_records.append({
            "name": hosp["name"], "lng": hosp["lng"], "lat": hosp["lat"],
            "type": hosp.get("type", ""), "district": district,
            "dist_to_fault_km": round(dist_to_fault, 1),
            "buffer_km": hb, "accessibility": acc,
        })

    acc_df = pd.DataFrame(access_records)
    acc_df.to_csv(DATA_DIR / f"accessibility_{mag_str}.csv", index=False, encoding="utf-8-sig")

    acc_counts = acc_df["accessibility"].value_counts()
    road_counts = roads_w["block_level"].value_counts()
    print(f"  Access: unreachable={acc_counts.get('不可达',0)}, normal={acc_counts.get('正常可达',0)}")
    print(f"  Roads: full_block={road_counts.get('完全阻断',0)}, severe={road_counts.get('严重损伤',0)}, "
          f"mild={road_counts.get('轻度损伤',0)}, normal={road_counts.get('正常',0)}")

print("\n" + "=" * 60)
print("All magnitude scenarios regenerated!")
print(f"Output: {DATA_DIR}")
