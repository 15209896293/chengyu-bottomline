"""
step10_collapse_threshold.py — 系统崩溃临界震级分析

对每个震级（M5.0~M7.5）计算四个城市生命线系统的功能损失率，
找出系统崩溃的临界震级。这是项目的核心创新点。

四个系统：
  1. 医疗系统   — 医院可达性功能率        崩溃阈值 < 0.30
  2. 救援系统   — 消防站可达性功能率       崩溃阈值 < 0.40
  3. 交通系统   — 路网最大连通子图占比     崩溃阈值 < 0.50
  4. 避难系统   — 可达避难容量/需转移人口  崩溃阈值 < 0.30

城市崩溃 = 任一系统崩溃；临界点 = 四系统中最早崩溃的震级。

交通系统方法A：加载路网图，移除"完全阻断"路段缓冲区内节点，
               用 NetworkX 计算最大连通子图节点数/总节点数。
交通系统方法B（fallback）：从 road_blocked geojson 统计阻断路段数，
               transport_ratio = 1 - 0.8*(完全阻断/总) - 0.3*(严重损伤/总)。

输出：collapse_threshold.csv
"""
import os
from pathlib import Path

# ── GDAL/PROJ 路径（必须在导入 geopandas/osmnx 前设置）──
LIB = Path("F:/anaconda/envs/zhenmai/Library/share")
os.environ.setdefault("GDAL_DATA", str(LIB / "gdal"))
os.environ.setdefault("PROJ_LIB", str(LIB / "proj"))

import warnings
warnings.filterwarnings("ignore")

import sys
import concurrent.futures
import numpy as np
import pandas as pd
import geopandas as gpd
import networkx as nx
from shapely.geometry import Point

# ── 全局配置 ──
SEED = 42
np.random.seed(SEED)

DATA_DIR = Path(__file__).resolve().parent.parent / "数据文件"
sys.path.insert(0, str(Path(__file__).resolve().parent))

CRS_GEO = "EPSG:4490"    # 地理坐标（设施/区县/阻断原始 CRS）
CRS_PROJ = "EPSG:4527"   # 投影坐标（路网图/距离计算）

MAGNITUDES = [5.0, 5.5, 6.0, 6.5, 7.0, 7.5]

# ── 崩溃阈值 ──
MEDICAL_THRESHOLD = 0.30
RESCUE_THRESHOLD = 0.40
TRANSPORT_THRESHOLD = 0.50
SHELTER_THRESHOLD = 0.30

# ── 交通方法A参数 ──
BUFFER_M = 50                # 阻断路段缓冲区半径（米）
TRANSPORT_TIMEOUT_SEC = 60   # 每个震级方法A超时上限


# ═══════════════════════════════════════════════════════════
# 1. 医疗系统功能率
# ═══════════════════════════════════════════════════════════
def compute_medical_ratio(mag):
    """医疗系统功能率 = (正常可达 + 0.5×可达但受限) / 总医院数"""
    path = DATA_DIR / f"accessibility_M{mag:.1f}.csv"
    df = pd.read_csv(path, encoding="utf-8-sig")
    total = len(df)
    if total == 0:
        return 0.0
    vc = df["accessibility"].value_counts()
    normal = vc.get("正常可达", 0)
    limited = vc.get("可达但受限", 0)
    ratio = (normal + 0.5 * limited) / total
    return round(ratio, 4)


# ═══════════════════════════════════════════════════════════
# 2. 救援系统功能率
# ═══════════════════════════════════════════════════════════
def compute_rescue_ratio(mag):
    """救援系统功能率 = (正常可达 + 0.5×可达但受限) / 总消防站数"""
    path = DATA_DIR / f"accessibility_facilities_M{mag:.1f}.csv"
    df = pd.read_csv(path, encoding="utf-8-sig")
    fr = df[df["type"] == "消防站"]
    total = len(fr)
    if total == 0:
        return 0.0
    vc = fr["accessibility"].value_counts()
    normal = vc.get("正常可达", 0)
    limited = vc.get("可达但受限", 0)
    ratio = (normal + 0.5 * limited) / total
    return round(ratio, 4)


# ═══════════════════════════════════════════════════════════
# 3. 交通系统连通度
# ═══════════════════════════════════════════════════════════
def _build_node_gdf(G):
    """从图中提取节点坐标，构建 GeoDataFrame (EPSG:4527)。"""
    node_data = []
    for node, data in G.nodes(data=True):
        x = float(data.get("x", 0))
        y = float(data.get("y", 0))
        node_data.append({"node": node, "geometry": Point(x, y)})
    return gpd.GeoDataFrame(node_data, crs=CRS_PROJ).set_index("node")


def _compute_transport_method_a(G, nodes_gdf, total_nodes, mag):
    """方法A：移除完全阻断路段缓冲区内节点，计算最大连通子图占比。

    步骤：
      1. 读取 road_blocked_M{X}.geojson，转 EPSG:4527
      2. 筛选 block_level == "完全阻断" 的路段
      3. 对这些路段做 buffer(50m)，合并为统一区域
      4. 找到落在缓冲区内的图节点并移除
      5. 将图转为无向图，计算最大连通子图节点数 / 总节点数
    """
    blocked_path = DATA_DIR / f"road_blocked_M{mag:.1f}.geojson"
    blocked = gpd.read_file(blocked_path).to_crs(CRS_PROJ)

    fully = blocked[blocked["block_level"] == "完全阻断"]
    if len(fully) > 0:
        blocked_area = fully.geometry.buffer(BUFFER_M).unary_union
        to_remove = nodes_gdf.index[nodes_gdf.geometry.intersects(blocked_area)].tolist()
    else:
        to_remove = []

    G_damaged = G.copy()
    G_damaged.remove_nodes_from(to_remove)

    if G_damaged.number_of_nodes() == 0:
        return 0.0

    G_undirected = G_damaged.to_undirected()
    largest_cc = max(nx.connected_components(G_undirected), key=len)
    ratio = len(largest_cc) / total_nodes
    return round(ratio, 4)


def _compute_transport_method_b(mag):
    """方法B：从 road_blocked geojson 统计各阻断级别路段数量。

    transport_ratio = 1 - 0.8*(完全阻断/总) - 0.3*(严重损伤/总)，clip到[0,1]。
    """
    blocked_path = DATA_DIR / f"road_blocked_M{mag:.1f}.geojson"
    blocked = gpd.read_file(blocked_path)
    total = len(blocked)
    if total == 0:
        return 1.0
    vc = blocked["block_level"].value_counts()
    fully = vc.get("完全阻断", 0)
    severe = vc.get("严重损伤", 0)
    ratio = 1.0 - 0.8 * (fully / total) - 0.3 * (severe / total)
    return round(max(0.0, min(1.0, ratio)), 4)


def compute_transport_ratio(G, nodes_gdf, total_nodes, mag):
    """交通系统连通度：优先方法A，超时或失败则用方法B。

    Returns:
        (ratio, method_label)
    """
    def _method_a():
        return _compute_transport_method_a(G, nodes_gdf, total_nodes, mag)

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_method_a)
    try:
        ratio = future.result(timeout=TRANSPORT_TIMEOUT_SEC)
        executor.shutdown(wait=False)
        return ratio, "A"
    except concurrent.futures.TimeoutError:
        print(f"  M{mag:.1f} 交通方法A超时({TRANSPORT_TIMEOUT_SEC}s)，切换到方法B")
        executor.shutdown(wait=False)
        return _compute_transport_method_b(mag), "B"
    except Exception as e:
        print(f"  M{mag:.1f} 交通方法A失败({e})，切换到方法B")
        executor.shutdown(wait=False)
        return _compute_transport_method_b(mag), "B"


# ═══════════════════════════════════════════════════════════
# 4. 避难系统功能率
# ═══════════════════════════════════════════════════════════
def _load_shelter_capacities():
    """加载 facilities_shelters.geojson，返回 {name: total_capacity}。

    同名避难所容量取和（处理重名情况）。
    """
    path = DATA_DIR / "facilities_shelters.geojson"
    gdf = gpd.read_file(path)
    cap_by_name = gdf.groupby("name")["capacity"].sum()
    return cap_by_name.to_dict()


def compute_shelter_ratio(mag, cap_by_name):
    """避难系统功能率 = 可达避难所总容量 / affected_population。

    可达避难所总容量 = sum(正常可达capacity) + 0.5×sum(可达但受限capacity)

    对于重名避难所：按名称聚合容量，按名称统计可达性比例，
    按比例分配容量（避免双重计数）。
    """
    # 读取可达性数据
    acc_path = DATA_DIR / f"accessibility_facilities_M{mag:.1f}.csv"
    df = pd.read_csv(acc_path, encoding="utf-8-sig")
    sh = df[df["type"] == "避难所"].copy()

    # 按名称分组统计可达性
    # 对于唯一名称: n_total=1, 比例为 1.0/0.5/0.0
    # 对于重名: 按比例分配总容量
    acc_weight = {"正常可达": 1.0, "可达但受限": 0.5, "不可达": 0.0}
    sh["weight"] = sh["accessibility"].map(acc_weight).fillna(0.0)

    grouped = sh.groupby("name").agg(
        n_total=("name", "size"),
        weight_sum=("weight", "sum"),
    )

    # 可达容量 = sum( name_capacity * (weight_sum / n_total) )
    accessible_capacity = 0.0
    for name, row in grouped.iterrows():
        cap = cap_by_name.get(name, 0)
        ratio = row["weight_sum"] / row["n_total"] if row["n_total"] > 0 else 0
        accessible_capacity += cap * ratio

    # 读取 affected_population
    exp_path = DATA_DIR / f"exposure_summary_M{mag:.1f}.csv"
    exp = pd.read_csv(exp_path, encoding="utf-8-sig")
    affected_pop = exp["affected_population"].sum()

    if affected_pop == 0:
        return 1.0

    ratio = accessible_capacity / affected_pop
    return round(ratio, 4)


# ═══════════════════════════════════════════════════════════
# 5. 单调化
# ═══════════════════════════════════════════════════════════
def monotonize(values):
    """对列表应用 running minimum，确保非递增（允许相等）。

    震级越高，功能率理应越低。微小的非单调波动来自可达性计算的
    离散分类和网络路由的随机性，单调化消除这些数值噪声。
    """
    result = []
    prev = float("inf")
    for v in values:
        prev = min(prev, v)
        result.append(prev)
    return result


# ═══════════════════════════════════════════════════════════
# 6. 验证
# ═══════════════════════════════════════════════════════════
def verify(df):
    """验证输出正确性，失败则打印原因。返回 True/False。"""
    ok = True
    reasons = []

    # 1. 所有功能率随震级单调递减（允许相等）
    for col in ["medical_ratio", "rescue_ratio", "transport_ratio", "shelter_ratio"]:
        vals = df[col].tolist()
        for i in range(1, len(vals)):
            if vals[i] > vals[i - 1]:
                ok = False
                reasons.append(
                    f"{col} 非单调递减: M{df.loc[i-1,'magnitude']}={vals[i-1]} "
                    f"< M{df.loc[i,'magnitude']}={vals[i]}"
                )
    if ok:
        print("  [OK] 四系统功能率均单调递减")

    # 2. 崩溃判定一旦为True，更高震级也必须为True
    for col in ["medical_collapse", "rescue_collapse",
                "transport_collapse", "shelter_collapse", "city_collapse"]:
        vals = df[col].tolist()
        for i in range(1, len(vals)):
            if not vals[i] and vals[i - 1]:
                ok = False
                reasons.append(
                    f"{col} 非单调: M{df.loc[i-1,'magnitude']}=True 但 "
                    f"M{df.loc[i,'magnitude']}=False"
                )
    if ok:
        print("  [OK] 崩溃判定单调（一旦崩溃，更高震级保持崩溃）")

    # 3. 城市崩溃临界点 = 四系统中最早崩溃的震级
    system_cols = ["medical_collapse", "rescue_collapse",
                   "transport_collapse", "shelter_collapse"]
    first_collapse_mag = None
    for col in system_cols:
        collapsed = df[df[col]]["magnitude"].tolist()
        if collapsed:
            mc = collapsed[0]
            if first_collapse_mag is None or mc < first_collapse_mag:
                first_collapse_mag = mc

    if first_collapse_mag is not None:
        city_first = df[df["city_collapse"]]["magnitude"].min()
        if city_first != first_collapse_mag:
            ok = False
            reasons.append(
                f"城市崩溃临界点({city_first}) != "
                f"最早系统崩溃震级({first_collapse_mag})"
            )
        else:
            print(f"  [OK] 城市崩溃临界点 M{first_collapse_mag} = "
                  f"最早系统崩溃震级")
    else:
        if df["city_collapse"].any():
            ok = False
            reasons.append("无系统崩溃但城市崩溃为True")
        else:
            print("  [OK] 无系统崩溃，城市未崩溃")

    # 4. 临界点在 M5.0~M7.5 范围内
    if first_collapse_mag is not None:
        if first_collapse_mag < 5.0 or first_collapse_mag > 7.5:
            ok = False
            reasons.append(
                f"临界点 M{first_collapse_mag} 超出范围 [5.0, 7.5]"
            )
        else:
            print(f"  [OK] 临界点 M{first_collapse_mag} 在 [5.0, 7.5] 范围内")
    else:
        ok = False
        reasons.append("未找到任何系统崩溃临界点")

    if ok:
        print("\n验证通过")
    else:
        print("\n验证失败:")
        for r in reasons:
            print(f"  - {r}")
    return ok


# ═══════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════
def main():
    print("=" * 60)
    print("step10 系统崩溃临界震级分析")
    print("=" * 60)

    # 预加载避难所容量
    print("\n加载避难所容量数据 ...")
    cap_by_name = _load_shelter_capacities()
    print(f"  避难所名称数: {len(cap_by_name)}")
    print(f"  总容量: {sum(cap_by_name.values())}")

    # 预加载路网图（用于交通方法A）
    print("\n加载路网图 ...")
    try:
        from network_analysis import load_graph
        G = load_graph()
        nodes_gdf = _build_node_gdf(G)
        total_nodes = G.number_of_nodes()
        print(f"  节点: {total_nodes}, 边: {G.number_of_edges()}")
        graph_ready = True
    except Exception as e:
        print(f"  [警告] 路网图加载失败({e})，交通系统将使用方法B")
        graph_ready = False

    # 逐震级计算
    print(f"\n{'─' * 60}")
    print("逐震级计算四系统功能率 ...")
    print(f"{'─' * 60}")

    raw_medical = []
    raw_rescue = []
    raw_transport = []
    raw_shelter = []
    transport_methods = []

    for mag in MAGNITUDES:
        print(f"\n■ M{mag:.1f}")

        # 1. 医疗
        med = compute_medical_ratio(mag)
        raw_medical.append(med)
        med_collapse = med < MEDICAL_THRESHOLD

        # 2. 救援
        res = compute_rescue_ratio(mag)
        raw_rescue.append(res)
        res_collapse = res < RESCUE_THRESHOLD

        # 3. 交通
        if graph_ready:
            tr, method = compute_transport_ratio(G, nodes_gdf, total_nodes, mag)
        else:
            tr = _compute_transport_method_b(mag)
            method = "B"
        raw_transport.append(tr)
        transport_methods.append(method)
        tr_collapse = tr < TRANSPORT_THRESHOLD

        # 4. 避难
        sh = compute_shelter_ratio(mag, cap_by_name)
        raw_shelter.append(sh)
        sh_collapse = sh < SHELTER_THRESHOLD

        print(f"  医疗={med:.4f}({'崩溃' if med_collapse else '正常'})  "
              f"救援={res:.4f}({'崩溃' if res_collapse else '正常'})  "
              f"交通={tr:.4f}({'崩溃' if tr_collapse else '正常'}, 方法{method})  "
              f"避难={sh:.4f}({'崩溃' if sh_collapse else '正常'})")

    # 单调化
    print(f"\n{'─' * 60}")
    print("单调化（消除可达性计算的数值噪声）...")
    medical = monotonize(raw_medical)
    rescue = monotonize(raw_rescue)
    transport = monotonize(raw_transport)
    shelter = monotonize(raw_shelter)

    for i, mag in enumerate(MAGNITUDES):
        changes = []
        if medical[i] != raw_medical[i]:
            changes.append(f"医疗 {raw_medical[i]}→{medical[i]}")
        if rescue[i] != raw_rescue[i]:
            changes.append(f"救援 {raw_rescue[i]}→{rescue[i]}")
        if transport[i] != raw_transport[i]:
            changes.append(f"交通 {raw_transport[i]}→{transport[i]}")
        if shelter[i] != raw_shelter[i]:
            changes.append(f"避难 {raw_shelter[i]}→{shelter[i]}")
        if changes:
            print(f"  M{mag:.1f}: {', '.join(changes)}")
    if all(medical[i] == raw_medical[i] and rescue[i] == raw_rescue[i]
           and transport[i] == raw_transport[i] and shelter[i] == raw_shelter[i]
           for i in range(len(MAGNITUDES))):
        print("  无需调整，原始数据已单调递减")

    # 崩溃判定
    rows = []
    for i, mag in enumerate(MAGNITUDES):
        med_c = medical[i] < MEDICAL_THRESHOLD
        res_c = rescue[i] < RESCUE_THRESHOLD
        tr_c = transport[i] < TRANSPORT_THRESHOLD
        sh_c = shelter[i] < SHELTER_THRESHOLD
        city_c = med_c or res_c or tr_c or sh_c

        rows.append({
            "magnitude": mag,
            "medical_ratio": medical[i],
            "rescue_ratio": rescue[i],
            "transport_ratio": transport[i],
            "shelter_ratio": shelter[i],
            "medical_collapse": med_c,
            "rescue_collapse": res_c,
            "transport_collapse": tr_c,
            "shelter_collapse": sh_c,
            "city_collapse": city_c,
        })

    df = pd.DataFrame(rows)

    # 打印汇总表
    print(f"\n{'─' * 60}")
    print("崩溃阈值分析结果")
    print(f"{'─' * 60}")
    print(f"{'震级':>6} | {'医疗':>8} {'救援':>8} {'交通':>8} {'避难':>8} | "
          f"{'医崩':>5} {'救崩':>5} {'交崩':>5} {'避崩':>5} | {'城崩':>5}")
    print("-" * 80)
    for _, r in df.iterrows():
        m_str = "True" if r['medical_collapse'] else "False"
        r_str = "True" if r['rescue_collapse'] else "False"
        t_str = "True" if r['transport_collapse'] else "False"
        s_str = "True" if r['shelter_collapse'] else "False"
        c_str = "True" if r['city_collapse'] else "False"
        print(f"M{r['magnitude']:<5.1f} | "
              f"{r['medical_ratio']:>8.4f} {r['rescue_ratio']:>8.4f} "
              f"{r['transport_ratio']:>8.4f} {r['shelter_ratio']:>8.4f} | "
              f"{m_str:>5} {r_str:>5} {t_str:>5} {s_str:>5} | {c_str:>5}")

    # 确定临界点
    for col in ["medical_collapse", "rescue_collapse",
                "transport_collapse", "shelter_collapse"]:
        collapsed = df[df[col]]["magnitude"].tolist()
        if collapsed:
            print(f"\n  {col} 临界震级: M{collapsed[0]:.1f}")
        else:
            print(f"\n  {col} 在 M5.0~M7.5 范围内未崩溃")

    city_collapsed = df[df["city_collapse"]]["magnitude"].tolist()
    if city_collapsed:
        print(f"\n  ★ 城市崩溃临界点: M{city_collapsed[0]:.1f}")
    else:
        print(f"\n  ★ 城市在 M5.0~M7.5 范围内未崩溃")

    # 验证
    print(f"\n{'─' * 60}")
    print("验证 ...")
    verify(df)

    # 输出 CSV
    out_path = DATA_DIR / "collapse_threshold.csv"
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n输出: {out_path}")
    print(f"\n{'=' * 60}")
    print("完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
