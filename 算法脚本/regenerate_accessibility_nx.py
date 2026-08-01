"""
regenerate_accessibility_nx.py — 用 NetworkX 最短路径分析重新生成所有震级的可达性文件
替换原有 buffer 画圈判定
"""
import os, sys
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

DATA_DIR = Path(__file__).resolve().parent.parent / "数据文件"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from network_analysis import (
    load_graph, apply_earthquake_damage, snap_points_to_graph,
    compute_edge_fault_distances, multi_source_dijkstra,
)

CRS_PROJ = "EPSG:4527"


def regenerate_all(blocking_radius=10):
    """Regenerate accessibility files for all magnitudes using NetworkX analysis."""
    print("=" * 60)
    print("NetworkX-based accessibility regeneration")
    print("=" * 60)

    # Load graph
    G = load_graph()

    # Ensure fault distances are computed
    if not any("dist_to_fault_m" in data for _, _, _, data in G.edges(keys=True, data=True)):
        G = compute_edge_fault_distances(G)
        ox.save_graphml(G, DATA_DIR / "hefei_road_graph.graphml")
        print("  Saved graph with fault distances.")

    # Load hospitals
    hospitals = pd.read_csv(DATA_DIR / "hefei_hospital.csv")
    hosp_gdf = gpd.GeoDataFrame(
        hospitals,
        geometry=gpd.points_from_xy(hospitals["lng"], hospitals["lat"]),
        crs="EPSG:4326"
    ).to_crs(CRS_PROJ)

    # Load original accessibility for district names
    try:
        orig_acc = pd.read_csv(DATA_DIR / "accessibility.csv")
        name_to_dist = dict(zip(orig_acc["name"], orig_acc["district"])) if "district" in orig_acc.columns else {}
    except FileNotFoundError:
        print("    [skip] accessibility.csv 不存在，district 合并跳过")
        name_to_dist = {}

    magnitudes = [5.0, 5.5, 6.0, 6.5, 7.0, 7.5]

    for mag in magnitudes:
        mag_str = f"M{mag:.1f}"
        print(f"\n{'─'*40}")
        print(f"Processing {mag_str}...")

        # Apply earthquake damage
        G_damaged = apply_earthquake_damage(G, mag, blocking_radius)

        # Snap hospitals
        snap = snap_points_to_graph(G, hosp_gdf, max_dist_m=5000)

        valid_nodes = {i: n for i, n in snap.items() if n is not None}
        print(f"  Hospitals snapped: {len(valid_nodes)}/{len(hosp_gdf)}")

        # Multi-source Dijkstra from hospitals (post-quake)
        post_sources = list(valid_nodes.values())
        post_lengths = multi_source_dijkstra(G_damaged, post_sources)

        # Pre-quake multi-source
        pre_lengths = multi_source_dijkstra(G, post_sources)

        # Per-hospital classification
        results = []
        for idx, row in hosp_gdf.iterrows():
            name = row["name"]
            node = snap.get(idx)

            if node is None or node not in G:
                results.append({
                    "name": name,
                    "accessibility": "不可达",
                    "district": name_to_dist.get(name, "未知"),
                })
                continue

            # Pre-quake reach (within 1 hour = 3600 sec)
            try:
                pre_r = len(nx.single_source_dijkstra_path_length(
                    G, node, weight="travel_time", cutoff=3600
                ))
            except:
                pre_r = 0

            # Post-quake reach
            try:
                post_r = len(nx.single_source_dijkstra_path_length(
                    G_damaged, node, weight="travel_time", cutoff=3600
                ))
            except:
                post_r = 0

            # Classify
            if post_r == 0:
                acc = "不可达"
            elif pre_r > 0 and post_r / pre_r < 0.3:
                acc = "不可达"
            elif pre_r > 0 and post_r / pre_r < 0.7:
                acc = "可达但受限"
            else:
                acc = "正常可达"

            results.append({
                "name": name,
                "accessibility": acc,
                "district": name_to_dist.get(name, "未知"),
            })

        df = pd.DataFrame(results)
        out_path = DATA_DIR / f"accessibility_{mag_str}.csv"
        df.to_csv(out_path, index=False)

        # Stats
        stats = df["accessibility"].value_counts().to_dict()
        print(f"  正常可达: {stats.get('正常可达', 0)}")
        print(f"  可达但受限: {stats.get('可达但受限', 0)}")
        print(f"  不可达: {stats.get('不可达', 0)}")
        print(f"  Saved: {out_path}")

    print(f"\n{'='*60}")
    print("All magnitudes regenerated with NetworkX analysis.")
    print("="*60)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--radius", type=int, default=10, help="Blocking radius in km")
    args = parser.parse_args()
    regenerate_all(args.radius)
