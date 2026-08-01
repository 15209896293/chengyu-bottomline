"""
replace_population_gdp.py — 用真实统计年鉴数据替换模拟人口/GDP
数据来源：合肥市2024年统计年鉴、各区县2024年统计公报

分配方法：按现有模拟值的相对比例在同区县内分配，保持空间分布不变
"""
import os
from pathlib import Path
import warnings
warnings.filterwarnings("ignore")

LIB = Path("F:/anaconda/envs/zhenmai/Library/share")
os.environ.setdefault("GDAL_DATA", str(LIB / "gdal"))
os.environ.setdefault("PROJ_LIB", str(LIB / "proj"))

import numpy as np
import geopandas as gpd
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "数据文件"

# ── 合肥市2024年各区县统计数据 ──
# 来源：合肥市统计局2024年统计年鉴/各区县2024年统计公报
# 注：行政区划口径，不含高新区/经开区/新站高新区等功能区
REAL_DATA = {
    "蜀山区":  {"population": 108.4, "gdp": 1504.6},  # 万人, 亿元
    "包河区":  {"population": 134.2, "gdp": 1902.9},
    "庐阳区":  {"population": 74.4,  "gdp": 1323.8},
    "瑶海区":  {"population": 90.1,  "gdp": 804.2},
    "肥西县":  {"population": 101.5, "gdp": 1212.4},
    "长丰县":  {"population": 84.2,  "gdp": 1038.6},
    "肥东县":  {"population": 91.6,  "gdp": 922.5},
    "庐江县":  {"population": 88.4,  "gdp": 731.1},
    "巢湖市":  {"population": 72.7,  "gdp": 669.3},
}


def main():
    print("Loading data...")
    grid = gpd.read_file(DATA_DIR / "grid_base.geojson")
    districts = gpd.read_file(DATA_DIR / "hefei_districts_4490.geojson")

    # Assign district to each grid cell via centroid containment (1:1, no duplicates)
    grid_4326 = grid.to_crs("EPSG:4326").copy()
    d_4326 = districts.to_crs("EPSG:4326")

    print(f"  Grid cells: {len(grid_4326)}")
    print(f"  Districts: {len(d_4326)}")

    # Compute centroid for each grid cell
    centroids = grid_4326.geometry.centroid
    centroid_gdf = gpd.GeoDataFrame(geometry=centroids, crs="EPSG:4326")

    # Spatial join: which district contains each centroid?
    joined = gpd.sjoin(centroid_gdf, d_4326[["name", "geometry"]],
                       how="left", predicate="within")

    # For cells whose centroid is outside all districts, try intersects
    unassigned = joined["name"].isna()
    if unassigned.sum() > 0:
        print(f"  {unassigned.sum()} centroids outside districts, using nearest district...")
        for idx in joined[unassigned].index:
            pt = centroid_gdf.loc[idx, "geometry"]
            dists = d_4326.geometry.apply(lambda g: pt.distance(g))
            joined.loc[idx, "name"] = d_4326.loc[dists.idxmin(), "name"]

    # Copy population/gdp from the original grid (same index)
    joined["population"] = grid_4326["population"].values
    joined["gdp"] = grid_4326["gdp"].values
    joined["geometry"] = grid_4326["geometry"].values

    # Report current state
    print("\n=== Current (simulated) ===")
    for dname in REAL_DATA:
        mask = joined["name"] == dname
        cells = mask.sum()
        pop = joined.loc[mask, "population"].sum()
        gdp = joined.loc[mask, "gdp"].sum()
        print(f"  {dname}: {cells} cells, pop={pop/10000:.1f}万, gdp={gdp/10000:.0f}亿")

    # Replace with real data (proportional allocation within each district)
    print("\n=== Replacing with real data ===")
    for dname, real in REAL_DATA.items():
        mask = joined["name"] == dname
        cells = mask.sum()
        if cells == 0:
            print(f"  {dname}: NO CELLS FOUND! Skipping.")
            continue

        # Target values (convert 万→人, 亿→万)
        target_pop = real["population"] * 10000
        target_gdp = real["gdp"] * 10000 * 10000  # 亿 → 万 → 元

        # Current total
        cur_pop = joined.loc[mask, "population"].sum()
        cur_gdp = joined.loc[mask, "gdp"].sum()

        # Scale proportionally (preserve spatial distribution)
        if cur_pop > 0:
            pop_scale = target_pop / cur_pop
            joined.loc[mask, "population"] = joined.loc[mask, "population"] * pop_scale
        else:
            # Equal distribution if no existing data
            joined.loc[mask, "population"] = target_pop / cells

        if cur_gdp > 0:
            gdp_scale = target_gdp / cur_gdp
            joined.loc[mask, "gdp"] = joined.loc[mask, "gdp"] * gdp_scale
        else:
            joined.loc[mask, "gdp"] = target_gdp / cells

        new_pop = joined.loc[mask, "population"].sum()
        new_gdp = joined.loc[mask, "gdp"].sum()
        print(f"  {dname}: pop {pop_scale:.4f}x → {new_pop/10000:.1f}万 (target {real['population']}万), "
              f"gdp {gdp_scale:.4f}x → {new_gdp/1e8:.1f}亿 (target {real['gdp']}亿)")

    # Update the original grid GeoDataFrame (align by index)
    grid_out = grid.copy()
    grid_out["population"] = joined["population"]
    grid_out["gdp"] = joined["gdp"]

    # Verify totals
    total_pop = grid_out["population"].sum()
    total_gdp = grid_out["gdp"].sum()
    print(f"\n=== Final totals ===")
    print(f"  Population: {total_pop/10000:.1f}万 (was {REAL_DATA['蜀山区']['population'] + REAL_DATA['包河区']['population'] + REAL_DATA['庐阳区']['population'] + REAL_DATA['瑶海区']['population'] + REAL_DATA['肥西县']['population'] + REAL_DATA['长丰县']['population'] + REAL_DATA['肥东县']['population'] + REAL_DATA['庐江县']['population'] + REAL_DATA['巢湖市']['population']}万 target)")
    print(f"  GDP: {total_gdp/1e8:.1f}亿 (was {REAL_DATA['蜀山区']['gdp'] + REAL_DATA['包河区']['gdp'] + REAL_DATA['庐阳区']['gdp'] + REAL_DATA['瑶海区']['gdp'] + REAL_DATA['肥西县']['gdp'] + REAL_DATA['长丰县']['gdp'] + REAL_DATA['肥东县']['gdp'] + REAL_DATA['庐江县']['gdp'] + REAL_DATA['巢湖市']['gdp']}亿 target)")

    # Backup original
    backup_path = DATA_DIR / "grid_base_simulated_backup.geojson"
    if not backup_path.exists():
        grid.to_file(backup_path, driver="GeoJSON")
        print(f"  Backup saved: {backup_path}")

    # Save updated
    out_path = DATA_DIR / "grid_base.geojson"
    grid_out.to_file(out_path, driver="GeoJSON")
    print(f"  Updated: {out_path}")

    # Also save a CSV summary for reference
    summary = []
    for dname in sorted(REAL_DATA.keys()):
        mask = joined["name"] == dname
        summary.append({
            "district": dname,
            "population_wan": round(joined.loc[mask, "population"].sum() / 10000, 2),
            "gdp_yi": round(joined.loc[mask, "gdp"].sum() / 1e8, 2),
            "grid_cells": int(mask.sum()),
            "data_source": "合肥市2024年统计年鉴",
        })
    pd.DataFrame(summary).to_csv(DATA_DIR / "population_gdp_summary.csv", index=False, encoding="utf-8-sig")
    print(f"  Summary saved: population_gdp_summary.csv")

    print("\nDone.")


if __name__ == "__main__":
    main()
