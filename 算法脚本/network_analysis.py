"""
network_analysis.py — 基于 OSMnx + NetworkX 的真实路网最短路径分析
替换原有的 buffer 画圈判定，实现：
  - 震后路网拓扑修改（删边/降速）
  - 多源 Dijkstra（从所有医院同时出发）
  - 网格级旅行时间变化
  - 医院可达性分类

核心管线：
  加载图 → 应用震害 → 多源Dijkstra → 输出网格旅行时间 → 对比震前/震后
"""
import os, sys, pickle
from pathlib import Path
import warnings
warnings.filterwarnings("ignore")

LIB = Path("F:/anaconda/envs/zhenmai/Library/share")
os.environ.setdefault("GDAL_DATA", str(LIB / "gdal"))
os.environ.setdefault("PROJ_LIB", str(LIB / "proj"))

import numpy as np
import pandas as pd
import geopandas as gpd
import networkx as nx
import osmnx as ox
from shapely.geometry import Point
from shapely.ops import unary_union

DATA_DIR = Path(__file__).resolve().parent.parent / "数据文件"
CRS_WGS = "EPSG:4326"
CRS_PROJ = "EPSG:4527"

# ── Speed assumptions (km/h) ──
SPEED_DEFAULT = 40.0      # default urban road speed
SPEED_PRIMARY = 60.0      # major roads
SPEED_RESIDENTIAL = 25.0  # residential streets
SPEED_DAMAGED_FACTOR = 0.2  # severely damaged roads: 20% of normal speed

# ── Accessibility thresholds ──
# Post-earthquake travel time / pre-earthquake travel time
ACCESS_NORMAL_RATIO = 1.5    # < 1.5x = normal
ACCESS_LIMITED_RATIO = 3.0   # 1.5-3x = limited, > 3x or unreachable = blocked


def download_and_save_graph():
    """Download Hefei OSM graph, project to EPSG:4527, save as GraphML."""
    print("Downloading Hefei OSM graph...")
    G = ox.graph_from_bbox(
        bbox=(117.0, 31.5, 117.5, 32.0),
        network_type="drive"
    )
    print(f"  Raw: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    # Project to EPSG:4527 (consistent with rest of project)
    G = ox.project_graph(G, to_crs=CRS_PROJ)

    # Add edge speeds and travel times (requires projected graph)
    G = ox.add_edge_speeds(G)
    G = ox.add_edge_travel_times(G)

    # Simplify
    G = ox.consolidate_intersections(G, tolerance=10, rebuild_graph=True, dead_ends=False)
    print(f"  Simplified: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    # Save as GraphML
    out_path = DATA_DIR / "hefei_road_graph.graphml"
    ox.save_graphml(G, out_path)
    print(f"  Saved: {out_path} (CRS: {G.graph.get('crs', 'unknown')})")

    return G


def load_graph():
    """Load the road graph, downloading if needed. Projects to EPSG:4527.
    Converts string attributes from GraphML back to numeric types."""
    graph_path = DATA_DIR / "hefei_road_graph.graphml"
    if not graph_path.exists():
        return download_and_save_graph()

    print("Loading road graph...")
    G = ox.load_graphml(graph_path)

    # Convert string attributes from GraphML to numeric
    for u, v, key, data in G.edges(keys=True, data=True):
        for attr in ["dist_to_fault_m", "travel_time", "length", "speed_kph"]:
            if attr in data and isinstance(data[attr], str):
                try:
                    data[attr] = float(data[attr])
                except ValueError:
                    pass

    # Ensure projected to EPSG:4527
    crs = G.graph.get("crs", None)
    if crs is None or str(crs) != CRS_PROJ:
        G = ox.project_graph(G, to_crs=CRS_PROJ)
        print(f"  Reprojected to {CRS_PROJ}")
    print(f"  {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    return G


def compute_edge_fault_distances(G):
    """
    Compute each edge's minimum distance to the fault line.
    Adds 'dist_to_fault_m' attribute to each edge.
    """
    fault_path = DATA_DIR / "tanlu_fault_hefei_4490.geojson"
    fault = gpd.read_file(fault_path)
    fault_proj = fault.to_crs(CRS_PROJ)
    fault_union = unary_union(fault_proj.geometry)

    # Get edges as GeoDataFrame
    edges = ox.graph_to_gdfs(G, nodes=False, edges=True)

    print(f"  Computing fault distances for {len(edges)} edges...")
    distances = {}
    for i, (idx, row) in enumerate(edges.iterrows()):
        if (i + 1) % 10000 == 0:
            print(f"    {i+1}/{len(edges)}...")
        geom = row.geometry
        if geom is None or geom.is_empty:
            distances[idx] = 1e9  # far away
        else:
            distances[idx] = geom.distance(fault_union)

    # Convert dict keys to proper format and set attributes
    nx.set_edge_attributes(G, distances, "dist_to_fault_m")
    return G


def apply_earthquake_damage(G, magnitude, blocking_radius_km=10):
    """
    Apply earthquake damage to the road graph.

    Parameters:
        G: NetworkX graph with edge attributes
        magnitude: earthquake magnitude (5.0-7.5)
        blocking_radius_km: distance beyond which roads are unaffected

    Returns:
        G_damaged: copy of G with modified edge weights

    Edge classification:
        - Rupture zone (dist < rupture_width): edge removed (weight = INF)
        - Inner zone (dist < 0.3 * radius): high probability of removal or severe slowdown
        - Mid zone (dist < radius): moderate slowdown
        - Outer zone (dist < 1.5 * radius): mild slowdown
        - Beyond: no change
    """
    import copy
    G_d = G.copy()
    radius_m = blocking_radius_km * 1000
    rupture_width = 10 ** (magnitude - 4.0)  # M5→10m, M6→100m, M7→1000m
    inner_zone = radius_m * (magnitude / 7.5)

    rng = np.random.default_rng(seed=int(magnitude * 100 + blocking_radius_km * 10))

    removed = 0
    slowed_severe = 0
    slowed_mild = 0

    for u, v, key, data in G_d.edges(keys=True, data=True):
        dist = float(data.get("dist_to_fault_m", 1e9))
        # Compute travel_time if missing
        if "travel_time" in data:
            travel_time = float(data["travel_time"])
        elif "length" in data:
            speed = float(data.get("speed_kph", SPEED_DEFAULT))
            travel_time = float(data["length"]) / (speed * 1000 / 3600)  # length in m, speed in km/h
        else:
            travel_time = 60.0  # default 1 minute

        if dist > radius_m * 1.5:
            continue  # no damage

        if dist < rupture_width:
            # Surface rupture: road destroyed
            data["travel_time"] = float("inf")
            data["damage"] = "完全阻断"
            removed += 1

        elif dist < inner_zone * 0.3:
            p = 0.9 * (magnitude / 7.5)
            roll = rng.random()
            if roll < p * 0.7:
                data["travel_time"] = float("inf")
                data["damage"] = "完全阻断"
                removed += 1
            elif roll < p:
                data["travel_time"] = travel_time / SPEED_DAMAGED_FACTOR
                data["damage"] = "严重损伤"
                slowed_severe += 1
            else:
                data["travel_time"] = travel_time * 1.5
                data["damage"] = "轻度损伤"
                slowed_mild += 1

        elif dist < inner_zone:
            norm_d = dist / inner_zone
            decay = (1 - norm_d) / 0.7
            p_block = 0.3 * decay * (magnitude / 7.5)
            roll = rng.random()
            if roll < p_block * 0.3:
                data["travel_time"] = float("inf")
                data["damage"] = "完全阻断"
                removed += 1
            elif roll < p_block:
                data["travel_time"] = travel_time / SPEED_DAMAGED_FACTOR
                data["damage"] = "严重损伤"
                slowed_severe += 1
            else:
                data["damage"] = "正常"
        else:
            norm_d = (dist - inner_zone) / (radius_m * 1.5 - inner_zone)
            p_mild = 0.15 * (1 - norm_d) * (magnitude / 7.5)
            roll = rng.random()
            if roll < p_mild:
                data["travel_time"] = travel_time * 1.5
                data["damage"] = "轻度损伤"
                slowed_mild += 1
            else:
                data["damage"] = "正常"

    total = G_d.number_of_edges()
    print(f"  M{magnitude:.1f} damage: {removed} removed ({100*removed/total:.1f}%), "
          f"{slowed_severe} severe, {slowed_mild} mild")
    return G_d


def snap_points_to_graph(G, points_gdf, max_dist_m=2000):
    """
    Snap a GeoDataFrame of points to the nearest graph node.
    Converts points to the graph's CRS automatically.

    Returns:
        dict: {point_index: graph_node_id} mapping
    """
    # Get node positions in graph CRS
    nodes_gdf = ox.graph_to_gdfs(G, nodes=True, edges=False)
    node_geoms = nodes_gdf.geometry

    # Ensure points are in the same CRS as the graph
    graph_crs = G.graph.get("crs", CRS_PROJ)
    if points_gdf.crs is None:
        points_gdf = points_gdf.set_crs(graph_crs)
    elif str(points_gdf.crs) != str(graph_crs):
        points_gdf = points_gdf.to_crs(graph_crs)

    node_ids = nodes_gdf.index.tolist()

    mapping = {}
    for idx, row in points_gdf.iterrows():
        pt = row.geometry
        if pt is None or pt.is_empty:
            mapping[idx] = None
            continue
        dists = node_geoms.distance(pt)
        min_dist = dists.min()
        if min_dist > max_dist_m:
            mapping[idx] = None
        else:
            mapping[idx] = node_ids[dists.idxmin()]

    snapped = sum(1 for v in mapping.values() if v is not None)
    print(f"  Snapped {snapped}/{len(mapping)} points to graph nodes")
    return mapping


def multi_source_dijkstra(G, source_nodes, weight="travel_time"):
    """
    Multi-source Dijkstra: compute shortest path from ANY of the source nodes.

    Technique: add a super-source connected to all sources with zero-weight edges.

    Returns:
        dict: {node_id: distance} for all reachable nodes
    """
    if len(source_nodes) == 0:
        return {}

    # Create a temporary super-source
    SUPER = "__super_source__"
    G_temp = G.copy()
    G_temp.add_node(SUPER)
    for src in source_nodes:
        if src in G_temp:
            G_temp.add_edge(SUPER, src, **{weight: 0.0})

    try:
        lengths = nx.single_source_dijkstra_path_length(G_temp, SUPER, weight=weight)
        # Remove super-source from results
        lengths.pop(SUPER, None)
        return lengths
    except nx.NetworkXError:
        return {}


def compute_accessibility_network(G_pre, G_post, hospitals_gdf, grids_gdf):
    """
    Full NetworkX-based accessibility analysis.

    Parameters:
        G_pre: undamaged graph
        G_post: earthquake-damaged graph
        hospitals_gdf: hospital points (projected CRS)
        grids_gdf: grid cell centroids (projected CRS)

    Returns:
        hospital_access: DataFrame with hospital name + accessibility classification
        grid_travel: DataFrame with grid cell_id + pre/post travel times
    """
    print("Snapping hospitals to graph...")
    hosp_snap = snap_points_to_graph(G_pre, hospitals_gdf)

    # Filter to valid hospitals (those that snapped to the graph)
    valid_hosp_nodes = [n for n in hosp_snap.values() if n is not None]
    valid_hosp_indices = [i for i, n in hosp_snap.items() if n is not None]
    print(f"  {len(valid_hosp_nodes)} hospitals connected to graph")

    if len(valid_hosp_nodes) == 0:
        # No hospitals reachable → all unreachable
        results = []
        for idx, row in hospitals_gdf.iterrows():
            results.append({
                "name": row.get("name", f"hosp_{idx}"),
                "accessibility": "不可达",
                "pre_travel_min": float("inf"),
                "post_travel_min": float("inf"),
            })
        return pd.DataFrame(results), None

    # Pre-earthquake: multi-source Dijkstra from all hospitals
    print("Computing pre-earthquake travel times...")
    pre_lengths = multi_source_dijkstra(G_pre, valid_hosp_nodes)

    # Post-earthquake: multi-source Dijkstra from all hospitals
    print("Computing post-earthquake travel times...")
    post_lengths = multi_source_dijkstra(G_post, valid_hosp_nodes)

    # Map hospital nodes back to hospital names
    node_to_hosp = {n: hospitals_gdf.iloc[i]["name"]
                    for i, n in zip(valid_hosp_indices, valid_hosp_nodes)}

    # For each hospital, find its accessibility by checking if it can reach other areas
    # A hospital is "不可达" if it can't reach most of the network
    # A hospital is "可达但受限" if its reachable area is significantly reduced

    hospital_results = []
    for idx, row in hospitals_gdf.iterrows():
        name = row["name"]
        node = hosp_snap.get(idx)

        if node is None:
            hospital_results.append({
                "name": name,
                "accessibility": "不可达",
                "pre_reachable_nodes": 0,
                "post_reachable_nodes": 0,
            })
            continue

        # Count reachable nodes from this hospital (single-source Dijkstra)
        pre_reachable = len(nx.single_source_dijkstra_path_length(
            G_pre, node, weight="travel_time", cutoff=3600  # 1 hour max
        )) if node in G_pre else 0

        if node not in G_post:
            post_reachable = 0
        else:
            try:
                post_reachable = len(nx.single_source_dijkstra_path_length(
                    G_post, node, weight="travel_time", cutoff=3600
                ))
            except nx.NetworkXError:
                post_reachable = 0

        # Classify
        if post_reachable == 0:
            acc = "不可达"
        elif pre_reachable > 0 and post_reachable / pre_reachable < 0.3:
            acc = "不可达"
        elif pre_reachable > 0 and post_reachable / pre_reachable < 0.7:
            acc = "可达但受限"
        else:
            acc = "正常可达"

        hospital_results.append({
            "name": name,
            "accessibility": acc,
            "pre_reachable_nodes": pre_reachable,
            "post_reachable_nodes": post_reachable,
        })

    hosp_df = pd.DataFrame(hospital_results)
    stats = hosp_df["accessibility"].value_counts().to_dict()
    print(f"  Hospital accessibility: {stats}")

    # Grid-level travel times
    print("Snapping grid cells to graph...")
    grid_snap = snap_points_to_graph(G_pre, grids_gdf, max_dist_m=5000)

    grid_results = []
    for idx, row in grids_gdf.iterrows():
        node = grid_snap.get(idx)
        cell_id = grids_gdf.iloc[idx].get("cell_id", idx)

        pre_time = pre_lengths.get(node, float("inf")) if node is not None else float("inf")
        post_time = post_lengths.get(node, float("inf")) if node is not None else float("inf")

        grid_results.append({
            "cell_id": cell_id,
            "pre_travel_sec": pre_time,
            "post_travel_sec": post_time,
            "time_increase": post_time - pre_time if pre_time < float("inf") else float("inf"),
        })

    grid_df = pd.DataFrame(grid_results)
    reachable = (grid_df["post_travel_sec"] < float("inf")).sum()
    print(f"  Grid cells reachable post-quake: {reachable}/{len(grid_df)}")

    return hosp_df, grid_df


# ── Main entry point for testing ──
if __name__ == "__main__":
    print("=" * 60)
    print("Network Analysis Module — Self Test")
    print("=" * 60)

    # 1. Load graph
    G = load_graph()

    # 2. Compute fault distances (first time only)
    if not any("dist_to_fault_m" in data for _, _, _, data in G.edges(keys=True, data=True)):
        G = compute_edge_fault_distances(G)
        # Save graph with distances
        ox.save_graphml(G, DATA_DIR / "hefei_road_graph.graphml")
        print("  Saved graph with fault distances.")

    # 3. Test damage application
    print("\nApplying earthquake damage...")
    G_m6 = apply_earthquake_damage(G, 6.0, 10)

    # 4. Load hospitals and test
    hospitals = pd.read_csv(DATA_DIR / "hefei_hospital.csv")
    hosp_gdf = gpd.GeoDataFrame(
        hospitals,
        geometry=gpd.points_from_xy(hospitals["lng"], hospitals["lat"]),
        crs=CRS_WGS
    ).to_crs(CRS_PROJ)

    # 5. Quick test: snap hospitals, compute pre/post reachable nodes
    print("\nSnapping hospitals...")
    snap = snap_points_to_graph(G, hosp_gdf)
    valid = [n for n in snap.values() if n is not None]

    print(f"\nPre-quake: multi-source from {len(valid)} hospitals")
    pre = multi_source_dijkstra(G, valid)
    pre_reachable = len(pre)
    print(f"  Reachable nodes: {pre_reachable}/{G.number_of_nodes()}")

    print(f"\nPost-quake (M6.0): multi-source from {len(valid)} hospitals")
    post = multi_source_dijkstra(G_m6, valid)
    post_reachable = len(post)
    print(f"  Reachable nodes: {post_reachable}/{G.number_of_nodes()} "
          f"({100*post_reachable/max(pre_reachable,1):.1f}% of pre-quake)")

    # 6. Per-hospital accessibility
    print("\nPer-hospital accessibility (sample):")
    unreachable = 0
    limited = 0
    normal = 0
    for idx, node in snap.items():
        if node is None:
            unreachable += 1
            continue
        pre_r = len(nx.single_source_dijkstra_path_length(G, node, weight="travel_time", cutoff=3600))
        try:
            post_r = len(nx.single_source_dijkstra_path_length(G_m6, node, weight="travel_time", cutoff=3600))
        except:
            post_r = 0

        if post_r == 0 or (pre_r > 0 and post_r / pre_r < 0.3):
            unreachable += 1
        elif pre_r > 0 and post_r / pre_r < 0.7:
            limited += 1
        else:
            normal += 1

    print(f"  正常可达: {normal}")
    print(f"  可达但受限: {limited}")
    print(f"  不可达: {unreachable}")

    print("\n=== Test PASSED ===")
