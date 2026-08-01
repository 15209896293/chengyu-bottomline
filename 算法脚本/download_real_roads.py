"""
download_real_roads.py — 下载合肥 OSM 真实路网 + 生成 6 震级阻断场景
替换原有 29 段模拟路网，一次生成所有 road_blocked_M*.geojson

用法：
    python src/download_real_roads.py          # 完整流程
    python src/download_real_roads.py --roads-only   # 仅下载路网
    python src/download_real_roads.py --scenarios-only  # 仅重新生成场景（已有路网）
"""
import os, sys, argparse
from pathlib import Path
import warnings
warnings.filterwarnings("ignore")

LIB = Path("F:/anaconda/envs/zhenmai/Library/share")
os.environ.setdefault("GDAL_DATA", str(LIB / "gdal"))
os.environ.setdefault("PROJ_LIB", str(LIB / "proj"))

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import LineString, Point, MultiLineString
from shapely.ops import unary_union

DATA_DIR = Path(__file__).resolve().parent.parent / "数据文件"
CRS_GEO = "EPSG:4490"
CRS_PROJ = "EPSG:4527"
CRS_WGS = "EPSG:4326"

# ── Hefei bounding box ──
HEFEI_BBOX = dict(north=32.0, south=31.5, east=117.5, west=117.0)


def download_osm_roads():
    """Download Hefei road network from OSM and save as GeoJSON."""
    import osmnx as ox

    print("Downloading OSM roads for Hefei...")
    G = ox.graph_from_bbox(
        bbox=(HEFEI_BBOX["west"], HEFEI_BBOX["south"],
              HEFEI_BBOX["east"], HEFEI_BBOX["north"]),
        network_type="drive"
    )
    print(f"  Raw: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    # Convert edges to GeoDataFrame (each edge = one road segment)
    edges = ox.graph_to_gdfs(G, nodes=False, edges=True)
    edges = edges.reset_index(drop=True)

    # Keep only relevant columns (highway may be list, flatten it)
    cols = ["geometry", "name"]
    if "highway" in edges.columns:
        cols.append("highway")
    if "length" in edges.columns:
        cols.append("length")
    edges = edges[[c for c in cols if c in edges.columns]].copy()

    # highway can be a list (multiple tags) — take first
    if "highway" in edges.columns:
        edges["highway"] = edges["highway"].apply(
            lambda x: x[0] if isinstance(x, list) and len(x) > 0 else str(x)
        )

    # Filter: only LineString
    edges = edges[edges.geometry.type == "LineString"].copy()

    # Compute length from geometry (in meters, projected)
    edges_proj_for_len = edges.set_crs(CRS_WGS).to_crs(CRS_PROJ)
    edges["length_m"] = edges_proj_for_len.geometry.length

    # Add road_id
    edges["road_id"] = range(len(edges))

    # Set CRS
    edges = edges.set_crs(CRS_WGS)

    # Convert to CGCS2000 geographic for storage
    edges_4490 = edges.to_crs(CRS_GEO)

    out_path = DATA_DIR / "hefei_roads_osm.geojson"
    edges_4490.to_file(out_path, driver="GeoJSON")
    print(f"  Saved: {out_path} ({len(edges_4490)} road segments)")

    # Quick stats
    print(f"  Total length: {edges.length_m.sum()/1000:.0f} km")
    if "highway" in edges.columns:
        print(f"  Top road types: {edges.highway.value_counts().head(8).to_dict()}")
    return edges_4490


def load_or_download_roads():
    """Load existing real roads, or download if missing."""
    path = DATA_DIR / "hefei_roads_osm.geojson"
    if path.exists():
        print(f"Loading existing real roads: {path}")
        return gpd.read_file(path)
    return download_osm_roads()


def compute_fault_distance(roads_gdf):
    """
    Compute minimum distance from each road segment to the fault line.
    Returns the roads GeoDataFrame with a `dist_to_fault_m` column.
    Handles potential memory issues by processing in chunks.
    """
    fault_path = DATA_DIR / "tanlu_fault_hefei_4490.geojson"
    if not fault_path.exists():
        raise FileNotFoundError(f"Fault file not found: {fault_path}")

    fault = gpd.read_file(fault_path)

    # Project to meters
    fault_proj = fault.to_crs(CRS_PROJ)
    fault_union = unary_union(fault_proj.geometry)
    roads_proj = roads_gdf.to_crs(CRS_PROJ).copy()

    print(f"Computing distances for {len(roads_proj)} roads to fault line...")

    # For 42K roads, individual distance() is fast (Shapely is C-backed)
    distances = []
    for i, geom in enumerate(roads_proj.geometry):
        if (i + 1) % 10000 == 0:
            print(f"  {i+1}/{len(roads_proj)}...")
        if geom is None or geom.is_empty:
            distances.append(float("inf"))
        else:
            distances.append(geom.distance(fault_union))

    roads_proj["dist_to_fault_m"] = distances

    # Convert back to geographic
    roads_out = roads_proj.to_crs(CRS_GEO)
    return roads_out


def assign_block_level(dist_m, magnitude, max_radius=20000):
    """
    Assign block_level to a road segment based on distance from fault
    and earthquake magnitude.

    Model:
      - Rupture zone: surface rupture = total destruction
      - Inner zone: heavy damage, probability decays with distance
      - Outer zone: moderate damage
      - Beyond max_radius: normal

    Magnitude affects:
      - Rupture zone width (wider for higher M)
      - Inner zone extent (further for higher M)
      - Blocking probability (higher for higher M)

    Returns one of: "完全阻断", "严重损伤", "轻度损伤", "正常"
    """
    if dist_m == float("inf") or dist_m > max_radius * 1.5:
        return "正常"

    # Rupture zone width scales with magnitude (empirical)
    # M5.0 ~ 100m, M6.0 ~ 300m, M7.0 ~ 1500m, M7.5 ~ 4000m
    rupture_width = 10 ** (magnitude - 4.0)  # M5→10m, M6→100m, M7→1000m

    # Inner damage zone radius scales with magnitude
    inner_zone = max_radius * (magnitude / 7.5)  # M5→13.3km, M7.5→20km
    outer_zone = max_radius * min(1.5, 1.0 + (magnitude - 5.0) / 5.0)

    # Use fixed seed per road + magnitude for reproducibility
    rng = np.random.default_rng(seed=int(dist_m * 1000 + magnitude * 100))

    if dist_m < rupture_width:
        # Surface rupture zone — total destruction
        return "完全阻断"

    elif dist_m < inner_zone * 0.3:
        # Core damage zone
        p = 0.9 * (magnitude / 7.5)  # Higher M = higher P
        roll = rng.random()
        if roll < p:
            return "完全阻断"
        elif roll < p + (1 - p) * 0.5:
            return "严重损伤"
        else:
            return "轻度损伤"

    elif dist_m < inner_zone:
        # Medium damage zone
        # Probability decays with distance: P(d) = (1 - d/inner_zone)^power
        normalized_d = dist_m / inner_zone  # 0.3 to 1.0
        decay = (1 - normalized_d) / 0.7  # 1.0 at zone start, 0.0 at zone end
        p_block = 0.3 * decay * (magnitude / 7.5)

        roll = rng.random()
        if roll < p_block * 0.4:
            return "严重损伤"
        elif roll < p_block:
            return "轻度损伤"
        else:
            return "正常"

    elif dist_m < outer_zone:
        # Outer zone — minor damage only
        normalized_d = (dist_m - inner_zone) / (outer_zone - inner_zone)
        p_mild = 0.15 * (1 - normalized_d) * (magnitude / 7.5)

        roll = rng.random()
        if roll < p_mild:
            return "轻度损伤"
        else:
            return "正常"

    else:
        return "正常"


def generate_scenario(roads_gdf, magnitude, fault_path):
    """
    Generate a complete scenario for one magnitude:
      - road_blocked: roads with assigned block_level
      - accessibility: hospital accessibility (placeholder — recomputed at runtime)
    """
    mag_str = f"M{magnitude:.1f}"
    print(f"\n  Generating scenario {mag_str}...")

    # Assign block levels
    roads = roads_gdf.copy()
    roads["block_level"] = roads["dist_to_fault_m"].apply(
        lambda d: assign_block_level(d, magnitude)
    )

    # Save road GeoJSON
    road_out = DATA_DIR / f"road_blocked_{mag_str}.geojson"
    roads.to_file(road_out, driver="GeoJSON")

    # Stats
    counts = roads["block_level"].value_counts().to_dict()
    total = len(roads)
    print(f"    完全阻断: {counts.get('完全阻断', 0)} ({100*counts.get('完全阻断',0)/total:.1f}%)")
    print(f"    严重损伤: {counts.get('严重损伤', 0)} ({100*counts.get('严重损伤',0)/total:.1f}%)")
    print(f"    轻度损伤: {counts.get('轻度损伤', 0)} ({100*counts.get('轻度损伤',0)/total:.1f}%)")
    print(f"    正常:     {counts.get('正常', 0)} ({100*counts.get('正常',0)/total:.1f}%)")

    return roads


def generate_accessibility(roads_gdf, magnitude):
    """
    Compute hospital accessibility for this scenario.
    Uses the same logic as app.py's compute_accessibility.
    """
    mag_str = f"M{magnitude:.1f}"
    print(f"  Computing accessibility for {mag_str}...")

    hosp_path = DATA_DIR / "hefei_hospital.csv"
    if not hosp_path.exists():
        print("    No hospital data, skipping accessibility")
        return

    hospitals = pd.read_csv(hosp_path)
    hosp_gdf = gpd.GeoDataFrame(
        hospitals,
        geometry=gpd.points_from_xy(hospitals["lng"], hospitals["lat"]),
        crs=CRS_WGS
    ).to_crs(CRS_PROJ)

    # Filter blocked roads
    roads_proj = roads_gdf.to_crs(CRS_PROJ)
    blocked = roads_proj[roads_proj["block_level"] != "正常"]
    fb = blocked[blocked["block_level"] == "完全阻断"]
    sb = blocked[blocked["block_level"] == "严重损伤"]
    lb = blocked[blocked["block_level"] == "轻度损伤"]

    results = []
    # Use Shapely prepared geometry for speed
    from shapely import prepared
    fb_prep = prepared.prep(unary_union(fb.geometry)) if len(fb) > 0 else None
    sb_prep = prepared.prep(unary_union(sb.geometry)) if len(sb) > 0 else None
    lb_prep = prepared.prep(unary_union(lb.geometry)) if len(lb) > 0 else None

    buffer_m = 1000  # 1km buffer for road impact
    for _, row in hosp_gdf.iterrows():
        buf = row.geometry.buffer(buffer_m)

        if fb_prep is not None and fb_prep.intersects(buf):
            acc = "不可达"
        elif sb_prep is not None and sb_prep.intersects(buf):
            acc = "可达但受限"
        elif lb_prep is not None and lb_prep.intersects(buf):
            acc = "可达但受限"
        else:
            acc = "正常可达"

        # Find district (simple approach: use lat/lng)
        # We'll use the existing loss_estimate district mapping
        results.append({
            "name": row["name"],
            "accessibility": acc,
            "district": row.get("district", "未知"),
        })

    df = pd.DataFrame(results)

    # Merge with original hospital data to get district info from existing file
    orig_acc = pd.read_csv(DATA_DIR / "accessibility.csv")
    if "district" in orig_acc.columns:
        name_to_dist = dict(zip(orig_acc["name"], orig_acc["district"]))
        df["district"] = df["name"].map(name_to_dist).fillna("未知")

    out_path = DATA_DIR / f"accessibility_{mag_str}.csv"
    df.to_csv(out_path, index=False)

    stats = df["accessibility"].value_counts().to_dict()
    print(f"    正常可达: {stats.get('正常可达', 0)}")
    print(f"    可达但受限: {stats.get('可达但受限', 0)}")
    print(f"    不可达: {stats.get('不可达', 0)}")


def generate_all_scenarios(roads_gdf):
    """Generate road blocking scenarios for all 6 magnitudes."""
    magnitudes = [5.0, 5.5, 6.0, 6.5, 7.0, 7.5]
    print("\n" + "="*60)
    print("Generating 6 magnitude scenarios with real roads...")
    print("="*60)

    for mag in magnitudes:
        roads_with_blocks = generate_scenario(roads_gdf, mag, None)
        generate_accessibility(roads_with_blocks, mag)

    print("\nDone. All scenarios generated.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--roads-only", action="store_true")
    parser.add_argument("--scenarios-only", action="store_true")
    args = parser.parse_args()

    if args.scenarios_only:
        roads = load_or_download_roads()
        if "dist_to_fault_m" not in roads.columns:
            roads = compute_fault_distance(roads)
        generate_all_scenarios(roads)
    elif args.roads_only:
        download_osm_roads()
    else:
        # Full pipeline
        roads = download_osm_roads()
        roads = compute_fault_distance(roads)
        generate_all_scenarios(roads)


if __name__ == "__main__":
    main()
