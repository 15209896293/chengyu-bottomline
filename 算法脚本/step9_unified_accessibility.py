"""
step9_unified_accessibility.py — 统一可达性分析（NetworkX 图论方法）

将消防站、避难所、危险源的可达性计算从缓冲区方法升级为 NetworkX 图论方法，
与医院（regenerate_accessibility_nx.py）保持一致。

核心管线：
  加载路网图 → 读取 graph_nodes.csv → 读取三类设施 → 区县空间join + 断裂带距离
  → 对每个震级：按 road_blocked geojson 应用路网阻断（删节点/降速）
  → 多源 Dijkstra 计算每个设施到最近同类设施的最短旅行时间
  → 分类输出 accessibility_facilities_M{X}.csv
  → 末尾验证（不可达递增 / 9区县覆盖 / 无NaN）

阻断规则（空间匹配，因 graphml 边无 road_id 属性）：
  - "完全阻断"路段 buffer(50m)，删除中心落在缓冲区内的节点
  - "严重损伤"路段 buffer(50m)，相交边 travel_time × 3
  - "轻度损伤"路段 buffer(50m)，相交边 travel_time × 1.5

可达性判定（每个设施到最近的其他同类设施旅行时间 t）：
  - 设施 snap 节点被删除 / 1小时内无同类设施可达  → "不可达"，travel_time_min = 999
  - t > 30 分钟                                   → "可达但受限"
  - 否则                                           → "正常可达"
"""
import os
import sys
import traceback
from pathlib import Path

import warnings
warnings.filterwarnings("ignore")

# ── GDAL/PROJ 路径（必须在导入 geopandas/osmnx 前设置）──
LIB = Path("F:/anaconda/envs/zhenmai/Library/share")
os.environ.setdefault("GDAL_DATA", str(LIB / "gdal"))
os.environ.setdefault("PROJ_LIB", str(LIB / "proj"))

import numpy as np
import pandas as pd
import geopandas as gpd
import networkx as nx
import osmnx as ox
from shapely.ops import unary_union

# ── 全局配置 ──
SEED = 42
np.random.seed(SEED)

DATA_DIR = Path(__file__).resolve().parent.parent / "数据文件"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from network_analysis import load_graph, snap_points_to_graph  # noqa: E402

CRS_GEO = "EPSG:4490"   # 地理坐标（设施/区县/阻断/断裂带原始 CRS）
CRS_PROJ = "EPSG:4527"  # 投影坐标（路网图/距离计算）

MAGNITUDES = [5.0, 5.5, 6.0, 6.5, 7.0, 7.5]

# 路网阻断参数
BUFFER_M = 50            # 阻断路段缓冲区半径（米）
SEVERE_PENALTY = 3.0     # 严重损伤边权重惩罚系数
MILD_PENALTY = 1.5       # 轻度损伤边权重惩罚系数

# 可达性阈值
CUTOFF_SEC = 3600        # Dijkstra 截断（1小时），超过即视为孤立
LIMITED_THRESHOLD_SEC = 1800  # 30 分钟，超过为"可达但受限"

# 设施文件 → 输出 type 标签
FACILITY_FILES = {
    "facilities_rescue.geojson": "消防站",
    "facilities_shelters.geojson": "避难所",
    "facilities_hazards.geojson": "危险源",
}


# ═══════════════════════════════════════════════════════════
# 数据加载
# ═══════════════════════════════════════════════════════════
def load_facilities():
    """加载三类设施 GeoJSON，合并为单个 GeoDataFrame(EPSG:4490)，附 facility_type 列。"""
    frames = []
    for fname, ftype in FACILITY_FILES.items():
        fp = DATA_DIR / fname
        if not fp.exists():
            print(f"  [警告] 设施文件不存在: {fname}")
            continue
        gdf = gpd.read_file(fp)
        gdf["facility_type"] = ftype
        frames.append(gdf)
        print(f"  {fname}: {len(gdf)} 条 ({ftype})")
    if not frames:
        raise FileNotFoundError("未找到任何设施文件")
    all_fac = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=CRS_GEO)
    return all_fac


def assign_districts(fac_gdf):
    """通过 hefei_districts_4490.geojson 空间 join 确定设施所在区县。
    未匹配的点用最近区县兜底，避免 NaN。"""
    districts = gpd.read_file(DATA_DIR / "hefei_districts_4490.geojson")
    dist = districts[["name", "geometry"]].rename(columns={"name": "district"})
    joined = gpd.sjoin(fac_gdf, dist, how="left", predicate="within")

    # 兜底：落在区县边界外的点，取最近区县
    missing = joined.index[joined["district"].isna()].tolist()
    for idx in missing:
        pt = fac_gdf.loc[idx, "geometry"]
        d = districts.geometry.distance(pt)
        joined.at[idx, "district"] = districts.iloc[int(d.idxmin())]["name"]
    return joined


def compute_fault_distances(fac_gdf):
    """计算每个设施到郯庐断裂带的最短距离（公里）。"""
    fault = gpd.read_file(DATA_DIR / "tanlu_fault_hefei_4490.geojson").to_crs(CRS_PROJ)
    fault_union = unary_union(fault.geometry)
    fac_proj = fac_gdf.to_crs(CRS_PROJ)
    return (fac_proj.geometry.distance(fault_union) / 1000.0).round(2)


def load_graph_nodes():
    """读取 graph_nodes.csv 获取节点坐标（EPSG:4527），用于核对与最近节点查找。"""
    nodes_path = DATA_DIR / "graph_nodes.csv"
    if not nodes_path.exists():
        print("  [警告] graph_nodes.csv 不存在，跳过")
        return None
    nodes = pd.read_csv(nodes_path)
    print(f"  graph_nodes.csv: {len(nodes)} 个节点, 列={list(nodes.columns)}")
    return nodes


# ═══════════════════════════════════════════════════════════
# 路网阻断
# ═══════════════════════════════════════════════════════════
def apply_road_blocking(G, mag):
    """根据 road_blocked_M{mag}.geojson 应用震后路网阻断，返回受损图副本。

    - "完全阻断": buffer(50m) 内的节点删除
    - "严重损伤": buffer(50m) 相交边 travel_time × 3
    - "轻度损伤": buffer(50m) 相交边 travel_time × 1.5
    """
    blocked_path = DATA_DIR / f"road_blocked_M{mag:.1f}.geojson"
    if not blocked_path.exists():
        print(f"  [警告] 阻断文件不存在: {blocked_path.name}，跳过阻断")
        return G.copy()

    blocked = gpd.read_file(blocked_path).to_crs(CRS_PROJ)
    G_d = G.copy()

    # ── 完全阻断：删除缓冲区内的节点 ──
    fully = blocked[blocked["block_level"] == "完全阻断"]
    n_removed = 0
    if len(fully) > 0:
        blocked_area = fully.geometry.buffer(BUFFER_M).unary_union
        nodes_gdf = ox.graph_to_gdfs(G_d, nodes=True, edges=False)
        to_remove = nodes_gdf.index[nodes_gdf.geometry.intersects(blocked_area)].tolist()
        G_d.remove_nodes_from(to_remove)
        n_removed = len(to_remove)

    # ── 严重/轻度损伤：边权重惩罚（互斥，取最严重等级，避免双重惩罚）──
    severe = blocked[blocked["block_level"] == "严重损伤"]
    mild = blocked[blocked["block_level"] == "轻度损伤"]
    severe_area = severe.geometry.buffer(BUFFER_M).unary_union if len(severe) > 0 else None
    mild_area = mild.geometry.buffer(BUFFER_M).unary_union if len(mild) > 0 else None

    edges_gdf = ox.graph_to_gdfs(G_d, nodes=False, edges=True)
    geom = edges_gdf.geometry
    valid = geom.notna()

    severe_mask = valid & (geom.intersects(severe_area) if severe_area is not None else False)
    mild_mask = valid & ~severe_mask & (geom.intersects(mild_area) if mild_area is not None else False)

    n_severe = n_mild = 0
    for u, v, k in edges_gdf.index[severe_mask].tolist():
        if G_d.has_edge(u, v, k):
            tt = G_d[u][v][k].get("travel_time")
            if tt is not None:
                G_d[u][v][k]["travel_time"] = float(tt) * SEVERE_PENALTY
                n_severe += 1
    for u, v, k in edges_gdf.index[mild_mask].tolist():
        if G_d.has_edge(u, v, k):
            tt = G_d[u][v][k].get("travel_time")
            if tt is not None:
                G_d[u][v][k]["travel_time"] = float(tt) * MILD_PENALTY
                n_mild += 1

    print(f"  M{mag:.1f} 阻断: 删节点 {n_removed}, 严重损伤边 {n_severe}, 轻度损伤边 {n_mild}, "
          f"剩余 {G_d.number_of_nodes()} 节点 / {G_d.number_of_edges()} 边")
    return G_d


# ═══════════════════════════════════════════════════════════
# 可达性计算
# ═══════════════════════════════════════════════════════════
def compute_accessibility(G_damaged, fac_gdf, snap_map):
    """对每类设施，计算每个设施到最近的其他同类设施的最短旅行时间，分类可达性。

    Returns:
        DataFrame: name, type, district, accessibility, travel_time_min, dist_to_fault_km
    """
    results = []
    for ftype, grp in fac_gdf.groupby("facility_type"):
        # 该类设施 (idx, node) 列表（仅 snap 成功的）
        items = [(idx, snap_map.get(idx)) for idx in grp.index]
        items = [(idx, n) for idx, n in items if n is not None]
        n_total = len(grp)
        n_done = 0

        for i, (idx_i, node_i) in enumerate(items):
            n_done += 1
            if n_done % 50 == 0:
                print(f"    {ftype}: {n_done}/{len(items)}")

            row = fac_gdf.loc[idx_i]
            name = row.get("name", "")
            district = row.get("district", "未知")
            dist_fault = row.get("dist_to_fault_km", np.nan)

            # 设施节点被删除 → 不可达
            if node_i not in G_damaged:
                results.append(_record(name, ftype, district, "不可达", 999, dist_fault))
                continue

            # 从该设施出发的 Dijkstra（cutoff 加速）
            try:
                dist_i = nx.single_source_dijkstra_path_length(
                    G_damaged, node_i, weight="travel_time", cutoff=CUTOFF_SEC
                )
            except Exception:
                dist_i = {}

            # 到最近的其他同类设施时间（排除自身 idx）
            other_times = [
                dist_i[node_j]
                for j, (_, node_j) in enumerate(items)
                if j != i and node_j in dist_i
            ]

            if not other_times:
                # 1小时内无同类设施可达 → 孤立
                results.append(_record(name, ftype, district, "不可达", 999, dist_fault))
            else:
                tt_sec = min(other_times)
                tt_min = round(tt_sec / 60.0, 2)
                acc = "可达但受限" if tt_sec > LIMITED_THRESHOLD_SEC else "正常可达"
                results.append(_record(name, ftype, district, acc, tt_min, dist_fault))

        # snap 失败的设施（node 为 None）→ 不可达
        for idx in grp.index:
            if snap_map.get(idx) is None:
                row = fac_gdf.loc[idx]
                results.append(_record(
                    row.get("name", ""), ftype, row.get("district", "未知"),
                    "不可达", 999, row.get("dist_to_fault_km", np.nan),
                ))

    df = pd.DataFrame(results, columns=[
        "name", "type", "district", "accessibility", "travel_time_min", "dist_to_fault_km"
    ])
    return df


def _record(name, ftype, district, acc, tt_min, dist_fault):
    return {
        "name": name,
        "type": ftype,
        "district": district if pd.notna(district) else "未知",
        "accessibility": acc,
        "travel_time_min": tt_min,
        "dist_to_fault_km": round(dist_fault, 2) if pd.notna(dist_fault) else np.nan,
    }


# ═══════════════════════════════════════════════════════════
# 验证
# ═══════════════════════════════════════════════════════════
def verify(dfs_by_mag):
    """验证输出正确性，失败则打印原因。"""
    ok = True
    reasons = []

    # 1. M5.0 不可达数量 < M7.5 不可达数量
    df50 = dfs_by_mag.get(5.0)
    df75 = dfs_by_mag.get(7.5)
    if df50 is not None and df75 is not None:
        n50 = int((df50["accessibility"] == "不可达").sum())
        n75 = int((df75["accessibility"] == "不可达").sum())
        if not (n50 < n75):
            ok = False
            reasons.append(f"M5.0 不可达数({n50}) 应小于 M7.5 不可达数({n75})")
        else:
            print(f"  [OK] 不可达递增: M5.0={n50} < M7.5={n75}")
    else:
        ok = False
        reasons.append("缺少 M5.0 或 M7.5 输出，无法比较")

    # 2. 设施分布覆盖 9 个区县
    if df50 is not None:
        districts = df50["district"].dropna().unique()
        if len(districts) < 9:
            ok = False
            reasons.append(f"区县覆盖仅 {len(districts)} 个，应 9 个: {list(districts)}")
        else:
            print(f"  [OK] 区县覆盖 {len(districts)} 个: {sorted(districts)}")

    # 3. 无 NaN 值
    for mag, df in dfs_by_mag.items():
        na = int(df.isna().sum().sum())
        if na > 0:
            ok = False
            reasons.append(f"M{mag} 存在 {na} 个 NaN: {df.isna().sum().to_dict()}")
        else:
            print(f"  [OK] M{mag} 无 NaN")

    if ok:
        print("验证通过")
    else:
        print("验证失败:")
        for r in reasons:
            print(f"  - {r}")
    return ok


# ═══════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════
def main():
    print("=" * 60)
    print("step9 统一可达性分析 (NetworkX 图论方法)")
    print("=" * 60)

    # 1. 加载路网图
    try:
        G = load_graph()
    except Exception as e:
        print(f"[致命] 加载路网图失败: {e}")
        traceback.print_exc()
        return

    # 2. 读取 graph_nodes.csv 获取节点坐标
    try:
        load_graph_nodes()
    except Exception as e:
        print(f"  [警告] 读取 graph_nodes.csv 失败: {e}")

    # 3. 加载三类设施 + 区县归属 + 断裂带距离
    try:
        fac = load_facilities()
        fac = assign_districts(fac)
        fac["dist_to_fault_km"] = compute_fault_distances(fac).values
        print(f"  设施总数: {len(fac)}")
        print(f"  区县分布: {fac['district'].value_counts().to_dict()}")
    except Exception as e:
        print(f"[致命] 加载设施/区县/断裂带失败: {e}")
        traceback.print_exc()
        return

    # 4. snap 设施到路网节点（与医院方法一致，基于图节点几何）
    try:
        fac_proj = fac.to_crs(CRS_PROJ)
        snap_map = snap_points_to_graph(G, fac_proj, max_dist_m=5000)
    except Exception as e:
        print(f"[致命] 设施 snap 失败: {e}")
        traceback.print_exc()
        return

    # 5. 逐震级计算可达性
    dfs_by_mag = {}
    errors = []
    for mag in MAGNITUDES:
        try:
            print(f"\n{'─' * 40}")
            print(f"处理 M{mag:.1f} ...")
            G_d = apply_road_blocking(G, mag)
            df = compute_accessibility(G_d, fac, snap_map)

            out_path = DATA_DIR / f"accessibility_facilities_M{mag:.1f}.csv"
            df.to_csv(out_path, index=False, encoding="utf-8-sig")
            dfs_by_mag[mag] = df

            stats = df["accessibility"].value_counts().to_dict()
            print(f"  正常可达: {stats.get('正常可达', 0)}")
            print(f"  可达但受限: {stats.get('可达但受限', 0)}")
            print(f"  不可达: {stats.get('不可达', 0)}")
            print(f"  保存: {out_path.name}")
        except Exception as e:
            print(f"[错误] M{mag:.1f} 处理失败: {e}")
            traceback.print_exc()
            errors.append(f"M{mag:.1f}: {e}")

    # 6. 验证
    print(f"\n{'─' * 40}")
    print("验证输出 ...")
    if dfs_by_mag:
        try:
            verify(dfs_by_mag)
        except Exception as e:
            print(f"[错误] 验证过程异常: {e}")
            traceback.print_exc()

    # 汇总
    print(f"\n{'=' * 60}")
    if dfs_by_mag:
        print(f"完成 {len(dfs_by_mag)}/{len(MAGNITUDES)} 个震级")
    if errors:
        print(f"失败震级: {errors}")
    print("=" * 60)


if __name__ == "__main__":
    main()
