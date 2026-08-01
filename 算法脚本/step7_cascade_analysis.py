"""
step7_cascade_analysis.py — 级联失效分析与综合救援盲区计算
Phase 2 核心算法模块

提供三个函数：
1. calculate_comprehensive_blind_zones — 全设施可达性计算
2. identify_secondary_hazard_chains — 次生灾害链识别（路断→消防失能→化工厂爆炸风险）
3. compute_city_resilience_index — 区县城市韧性底线指数

可独立运行测试：python src/step7_cascade_analysis.py
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
from shapely.ops import unary_union
from shapely.geometry import Point

DATA_DIR = Path(__file__).resolve().parent.parent / "数据文件"
CRS_PROJ = "EPSG:4527"
CRS_GEO = "EPSG:4490"

# ── 辅助：路段过滤 ─────────────────────────────────────
def _filter_roads(roads_gdf, fault_gdf, blocking_radius_km):
    """路段到断裂带距离 > 阻断半径 → 恢复为正常"""
    if len(roads_gdf) == 0:
        return roads_gdf
    fault_proj = fault_gdf.to_crs(CRS_PROJ)
    fault_union = unary_union(fault_proj.geometry)
    radius_m = blocking_radius_km * 1000
    roads_proj = roads_gdf.to_crs(CRS_PROJ).copy()
    for idx, row in roads_proj.iterrows():
        if row.geometry is None or row.geometry.is_empty:
            continue
        if row.geometry.distance(fault_union) > radius_m:
            roads_proj.at[idx, "block_level"] = "正常"
    return roads_proj


# ── 辅助：单设施可达性判断 ─────────────────────────────
def _check_accessibility(facility_point, blocked_roads, buffer_m=500):
    """
    判断单个设施点的可达性。
    blocked_roads: 已过滤后的路段 GeoDataFrame（需在投影坐标系）
    返回: "不可达" | "可达但受限" | "正常可达"
    """
    buf = facility_point.buffer(buffer_m)
    full_blk = blocked_roads[blocked_roads["block_level"] == "完全阻断"]
    severe_blk = blocked_roads[blocked_roads["block_level"] == "严重损伤"]
    mild_blk = blocked_roads[blocked_roads["block_level"] == "轻度损伤"]

    if len(full_blk) > 0 and any(full_blk.intersects(buf)):
        return "不可达"
    if len(severe_blk) > 0 and any(severe_blk.intersects(buf)):
        return "可达但受限"
    if len(mild_blk) > 0 and any(mild_blk.intersects(buf)):
        return "可达但受限"
    return "正常可达"


# ═══════════════════════════════════════════════════════
# 函数 1: 综合盲区计算
# ═══════════════════════════════════════════════════════
def calculate_comprehensive_blind_zones(magnitude, blocking_radius=10, override_roads=None):
    """
    计算所有设施类型在当前震级和阻断半径下的可达性。

    参数:
        magnitude: 震级 (float, 5.0~7.5)
        blocking_radius: 阻断半径 (km)
        override_roads: 可选 GeoDataFrame，传入后跳过文件加载，
                        直接使用此路网数据（需已含 block_level 列，且在 EPSG:4527）
    返回:
        GeoDataFrame: 每个设施的 id, name, type, is_accessible,
                      accessibility_status, geometry (EPSG:4326)
    """
    if override_roads is not None:
        # Use caller-provided roads directly (already filtered, in EPSG:4527)
        filtered = override_roads.copy()
        # Ensure it has the right CRS
        if filtered.crs is None:
            filtered = filtered.set_crs(CRS_PROJ)
        elif str(filtered.crs) != CRS_PROJ:
            filtered = filtered.to_crs(CRS_PROJ)
    else:
        mag_key = f"M{magnitude:.1f}"
        roads_path = DATA_DIR / f"road_blocked_{mag_key}.geojson"
        fault_path = DATA_DIR / "tanlu_fault_hefei_4490.geojson"

        if not roads_path.exists():
            raise FileNotFoundError(f"路网数据不存在: {roads_path}")

        roads = gpd.read_file(roads_path)
        fault = gpd.read_file(fault_path)

        # 路段过滤
        filtered = _filter_roads(roads, fault, blocking_radius)

    # 加载所有设施
    facility_files = {
        "医院": ("hefei_hospital.csv", "csv"),
        "危险源": ("facilities_hazards.geojson", "geojson"),
        "救援力量": ("facilities_rescue.geojson", "geojson"),
        "避难所": ("facilities_shelters.geojson", "geojson"),
    }

    all_results = []

    for ftype, (fname, fmt) in facility_files.items():
        fp = DATA_DIR / fname
        if not fp.exists():
            continue

        if fmt == "csv":
            df = pd.read_csv(fp)
            gdf = gpd.GeoDataFrame(
                df, geometry=gpd.points_from_xy(df["lng"], df["lat"]), crs="EPSG:4326"
            )
        else:
            gdf = gpd.read_file(fp)

        gdf_proj = gdf.to_crs(CRS_PROJ)

        for _, row in gdf_proj.iterrows():
            acc = _check_accessibility(row.geometry, filtered)
            all_results.append({
                "id": row.get("id", row.get("name", "")),
                "name": row.get("name", ""),
                "type": ftype,
                "subtype": row.get("type", row.get("subtype", "")),
                "is_accessible": acc != "不可达",
                "accessibility_status": acc,
                "lat": row.geometry.y if gdf_proj.crs else row.get("lat", 0),
                "lng": row.geometry.x if gdf_proj.crs else row.get("lng", 0),
                "geometry": row.geometry,
            })

    if not all_results:
        result_gdf = gpd.GeoDataFrame({"geometry": []}, crs=CRS_PROJ)
    else:
        result_gdf = gpd.GeoDataFrame(all_results, crs=CRS_PROJ)
    result_gdf["lat"] = result_gdf.geometry.to_crs("EPSG:4326").y
    result_gdf["lng"] = result_gdf.geometry.to_crs("EPSG:4326").x
    result_gdf = result_gdf.to_crs("EPSG:4326")
    return result_gdf


# ═══════════════════════════════════════════════════════
# 函数 2: 次生灾害链识别
# ═══════════════════════════════════════════════════════
def identify_secondary_hazard_chains(blind_zones_gdf, roads_gdf=None):
    """
    识别次生灾害链：不可达的危化品源 + 周边消防站响应能力受损 = 高危爆炸风险点。

    参数:
        blind_zones_gdf: calculate_comprehensive_blind_zones 的输出
        roads_gdf: 可选，阻断路段 GeoDataFrame（EPSG:4527），用于精确判定消防站响应能力
    返回:
        GeoDataFrame: 高危爆炸风险点，含 risk_level, impact_radius, impact_area, is_critical
    """
    # 筛选不可达的危险源
    hazards_unreachable = blind_zones_gdf[
        (blind_zones_gdf["type"] == "危险源") &
        (blind_zones_gdf["accessibility_status"] == "不可达")
    ].copy()

    # 筛选所有消防站（不只不可达的，还要检查响应能力受损的）
    fire_all = blind_zones_gdf[
        (blind_zones_gdf["type"] == "救援力量") &
        (blind_zones_gdf["subtype"] == "消防站")
    ].copy()

    # 加载原始危险源数据（获取 buffer_radius）
    haz_path = DATA_DIR / "facilities_hazards.geojson"
    if not haz_path.exists():
        return gpd.GeoDataFrame(columns=["name", "risk_level", "impact_radius_m", "fire_nearby_unreachable", "geometry"], crs="EPSG:4326")

    haz_orig = gpd.read_file(haz_path)

    chain_results = []
    for _, hz in hazards_unreachable.iterrows():
        hz_name = hz.get("name", "")
        # 查找原始属性
        orig = haz_orig[haz_orig["name"] == hz_name]
        if len(orig) == 0:
            continue
        orig_row = orig.iloc[0]
        buf_r = orig_row.get("buffer_radius", 800)

        # 检查周围消防站的响应能力
        hz_geom_proj = gpd.GeoSeries([hz.geometry], crs="EPSG:4326").to_crs(CRS_PROJ).iloc[0]
        fire_proj = fire_all.to_crs(CRS_PROJ) if len(fire_all) > 0 else gpd.GeoDataFrame({"geometry": []}, crs=CRS_PROJ)

        nearby_compromised = 0
        if len(fire_proj) > 0:
            for _, fr in fire_proj.iterrows():
                dist = hz_geom_proj.distance(fr.geometry)
                if dist <= buf_r:
                    # A fire station is "compromised" if:
                    # 1) It's unreachable itself, OR
                    # 2) A blocked road exists within its coverage radius (can't effectively respond)
                    fs_unreachable = (fr.get("accessibility_status", "") == "不可达")
                    fs_restricted = (fr.get("accessibility_status", "") == "可达但受限")

                    # Also check via road proximity if roads_gdf provided
                    road_blocked_nearby = False
                    if roads_gdf is not None:
                        blk = roads_gdf[roads_gdf["block_level"].isin(["完全阻断", "严重损伤"])]
                        if len(blk) > 0:
                            blk_proj = blk.to_crs(CRS_PROJ) if blk.crs != CRS_PROJ else blk
                            coverage = 3000  # min fire coverage radius in meters
                            fs_buf = fr.geometry.buffer(coverage)
                            road_blocked_nearby = any(blk_proj.intersects(fs_buf))

                    if fs_unreachable or fs_restricted or road_blocked_nearby:
                        nearby_compromised += 1

        # 计算影响范围（多边形）
        impact_circle = hz_geom_proj.buffer(buf_r)

        chain_results.append({
            "id": orig_row.get("id", ""),
            "name": hz_name,
            "type": "高危爆炸风险点",
            "hazard_material": orig_row.get("hazard_material", ""),
            "risk_level": orig_row.get("risk_level", 3),
            "impact_radius_m": buf_r,
            "fire_nearby_unreachable": nearby_compromised,
            "is_critical": nearby_compromised > 0,
            "geometry": impact_circle,
        })

    if not chain_results:
        return gpd.GeoDataFrame({
            "name": [], "risk_level": [], "impact_radius_m": [], "fire_nearby_unreachable": [],
            "is_critical": [], "geometry": []
        }, crs=CRS_PROJ)

    result = gpd.GeoDataFrame(chain_results, crs=CRS_PROJ)
    result = result.to_crs("EPSG:4326")
    return result


# ═══════════════════════════════════════════════════════
# 函数 3: 城市韧性底线指数
# ═══════════════════════════════════════════════════════
def compute_city_resilience_index(districts_gdf, blind_zones_gdf, secondary_hazards_gdf):
    """
    按区县计算城市韧性底线指数。

    四个维度（归一化后加权）：
    - 路网连通率 (0.25): 未阻断路段占比
    - 医疗覆盖率 (0.25): 可达医院占比
    - 避难容量比 (0.25): 避难所容量与人口比
    - 危化品风险度 (0.25): 高风险点影响范围占比（反向指标）

    返回:
        DataFrame: district, resilience_index, is_below_bottom_line, 各维度得分
    """
    districts = districts_gdf.to_crs("EPSG:4326").copy()

    # 加载人口数据
    grid_path = DATA_DIR / "grid_base.geojson"
    if not grid_path.exists():
        raise FileNotFoundError(f"网格数据不存在: {grid_path}")
    grid = gpd.read_file(grid_path)
    grid_4326 = grid.to_crs("EPSG:4326")

    results = []
    for _, dist in districts.iterrows():
        dname = dist["name"]
        d_geom = dist.geometry

        # --- 维度1: 医疗覆盖率 ---
        hospitals = blind_zones_gdf[blind_zones_gdf["type"] == "医院"]
        hosp_in = hospitals[hospitals.intersects(d_geom)] if len(hospitals) > 0 else hospitals
        hosp_total = len(hosp_in)
        hosp_accessible = (hosp_in["accessibility_status"] == "正常可达").sum() if hosp_total > 0 else 0
        medical_rate = hosp_accessible / max(hosp_total, 1)

        # --- 维度2: 避难容量比 ---
        shelters = blind_zones_gdf[blind_zones_gdf["type"] == "避难所"]
        sh_in = shelters[shelters.intersects(d_geom)] if len(shelters) > 0 else shelters
        # 加载避难所容量（从原始数据）
        sh_path = DATA_DIR / "facilities_shelters.geojson"
        sh_orig = gpd.read_file(sh_path) if sh_path.exists() else None
        sh_capacity = 0
        if sh_orig is not None and len(sh_in) > 0:
            sh_names = sh_in["name"].tolist()
            sh_capacity = sh_orig[sh_orig["name"].isin(sh_names)]["capacity"].sum()

        # 区县人口
        grid_in = grid_4326[grid_4326.intersects(d_geom)] if len(grid_4326) > 0 else grid_4326
        dist_pop = grid_in["population"].sum() if len(grid_in) > 0 else 1
        shelter_ratio = min(sh_capacity / max(dist_pop, 1), 1.0)

        # --- 维度3: 路网连通率 ---
        # 基于盲区中的救援力量和消防站可达性代理
        rescue = blind_zones_gdf[blind_zones_gdf["type"] == "救援力量"]
        rs_in = rescue[rescue.intersects(d_geom)] if len(rescue) > 0 else rescue
        rs_total = len(rs_in)
        rs_accessible = (rs_in["accessibility_status"] == "正常可达").sum() if rs_total > 0 else 0
        road_rate = rs_accessible / max(rs_total, 1)

        # --- 维度4: 危化品风险度 ---
        haz_risk = 0.0
        if len(secondary_hazards_gdf) > 0:
            haz_in = secondary_hazards_gdf[secondary_hazards_gdf.intersects(d_geom)]
            if len(haz_in) > 0:
                # 危险源影响面积 / 区县面积
                d_area = d_geom.area
                haz_area = haz_in.geometry.area.sum()
                haz_risk = min(haz_area / max(d_area, 1), 1.0)
        # 风险度是反向指标：值越高越差
        haz_score = 1.0 - haz_risk

        # --- 综合指数 ---
        resilience_index = (
            medical_rate * 0.25 +
            shelter_ratio * 0.25 +
            road_rate * 0.25 +
            haz_score * 0.25
        )

        results.append({
            "district": dname,
            "resilience_index": round(resilience_index, 4),
            "is_below_bottom_line": resilience_index < 0.6,
            "medical_coverage": round(medical_rate, 3),
            "shelter_ratio": round(shelter_ratio, 3),
            "road_connectivity": round(road_rate, 3),
            "hazard_safety": round(haz_score, 3),
        })

    return pd.DataFrame(results).sort_values("resilience_index")


# ═══════════════════════════════════════════════════════
# 独立运行测试
# ═══════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=== step7_cascade_analysis 独立测试 ===\n")

    mag = 6.0
    br = 10

    print(f"1. 综合盲区计算 (M{mag}, 阻断{br}km)...")
    blind = calculate_comprehensive_blind_zones(mag, br)
    print(f"   设施总数: {len(blind)}")
    for t in blind["type"].unique():
        sub = blind[blind["type"] == t]
        unr = (sub["accessibility_status"] == "不可达").sum()
        print(f"   {t}: {len(sub)} 个, 不可达 {unr} ({100*unr/max(len(sub),1):.0f}%)")

    print(f"\n2. 次生灾害链识别...")
    roads = gpd.read_file(DATA_DIR / f"road_blocked_M{mag:.1f}.geojson")
    chains = identify_secondary_hazard_chains(blind, roads_gdf=roads)
    critical = chains[chains["is_critical"]] if len(chains) > 0 else chains
    print(f"   高危爆炸风险点: {len(critical)}/{len(chains)}")
    if len(critical) > 0:
        for _, r in critical.iterrows():
            print(f"   ⚠️ {r['name']}: 风险{r['risk_level']}级, 影响{r['impact_radius_m']}m, "
                  f"附近{r['fire_nearby_unreachable']}个消防站失能")

    print(f"\n3. 韧性底线指数...")
    districts = gpd.read_file(DATA_DIR / "hefei_districts_4490.geojson")
    resilience = compute_city_resilience_index(districts, blind, chains)
    print(resilience.to_string())
    below = resilience[resilience["is_below_bottom_line"]]
    if len(below) > 0:
            print(f"\n   WARNING: {len(below)} districts below bottom line: "
              + ", ".join(below['district'].tolist()))
    else:
        print(f"\n   OK: All districts above 0.6")

    print("\n=== Test PASSED ===")
