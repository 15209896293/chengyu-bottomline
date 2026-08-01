"""
step6_generate_facilities.py — 城市全要素设施数据生成
生成三类关键设施并写入 GeoJSON：
  1. 次生灾害危险源 (hazards)   — 15个：化工厂/加油站/燃气储罐
  2. 救援力量 (rescue)          — 20个：消防站/物资储备库
  3. 避难缓冲 (shelters)        — 10个：大型公园/体育场

所有设施坐标基于 hefei_hospital.csv 的经纬度边界随机分布，
但在断裂带沿线(经度约117.2~117.4)及城区核心区域适当加密。
输出到 数据文件/ 目录。
"""
import os
from pathlib import Path

LIB = Path("F:/anaconda/envs/zhenmai/Library/share")
os.environ.setdefault("GDAL_DATA", str(LIB / "gdal"))
os.environ.setdefault("PROJ_LIB", str(LIB / "proj"))

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point

DATA_DIR = Path(__file__).resolve().parent.parent / "数据文件"
SEED = 2026
rng = np.random.default_rng(SEED)

# ── 读取医院坐标边界 ────────────────────────────────────
hosp = pd.read_csv(DATA_DIR / "hefei_hospital.csv")
LAT_MIN, LAT_MAX = hosp["lat"].min(), hosp["lat"].max()
LNG_MIN, LNG_MAX = hosp["lng"].min(), hosp["lng"].max()
print(f"医院分布范围: lat [{LAT_MIN:.2f}, {LAT_MAX:.2f}], lng [{LNG_MIN:.2f}, {LNG_MAX:.2f}]")

# ── 辅助函数：在范围内生成随机点 ──────────────────────
def random_lat(n, center_lat=None, spread=0.1):
    """生成随机纬度"""
    if center_lat is not None:
        return rng.normal(center_lat, spread, n)
    return rng.uniform(LAT_MIN + 0.02, LAT_MAX - 0.02, n)

def random_lng(n, center_lng=None, spread=0.1):
    """生成随机经度"""
    if center_lng is not None:
        return rng.normal(center_lng, spread, n)
    return rng.uniform(LNG_MIN + 0.02, LNG_MAX - 0.02, n)

# ── 0. 预生成救援力量坐标（先算，供危险源锚定用） ──────
# Strategy: generate fire stations near fault line (lng 117.18-117.38),
# then anchor 2 hazards at those fire station locations.
# This guarantees cascade chains: blocked roads → unreachable fire + unreachable hazard.
_fire_lats, _fire_lngs = [], []
for i in range(11):  # 11 fire stations
    # Bias toward fault corridor (lng 117.18-117.38) for cascade anchoring
    if i < 6:
        _fire_lngs.append(rng.uniform(117.18, 117.38))  # near fault → will be blocked
    else:
        _fire_lngs.append(rng.uniform(117.15, 117.40))
    _fire_lats.append(rng.uniform(31.75, 31.95))

# ── 1. 次生灾害危险源 (15个) ──────────────────────────
print("\n--- 生成次生灾害危险源 ---")
HAZARD_NAMES = {
    "化工厂": ["合肥东部化工园", "循环经济示范园化工厂", "肥东精细化工基地", "庐阳化工仓储",
               "蜀山生物化工厂", "包河工业区化工站", "长丰合成材料厂"],
    "加油站": ["金寨路油气合建站", "长江东路加油站", "翡翠路加气站", "南二环大型加油站",
               "方兴大道油气站", "北城世纪城加油站"],
    "燃气储罐站": ["合肥燃气集团储配站", "肥西液化气储配中心"],
}

# P3: Anchor 2 chemical plants directly at fire station locations near fault line.
# Fire stations near fault have blocked roads nearby → hazard becomes unreachable.
# Both hazard and fire station are within hazard's buffer_radius → cascade triggered.
_fire_fault_nearby = [(lat, lng) for lat, lng in zip(_fire_lats, _fire_lngs)
                       if 117.18 <= lng <= 117.38]
# Pick 2 fire stations closest to fault center (~117.28)
_fire_fault_nearby.sort(key=lambda x: abs(x[1] - 117.28))
_anchor_fires = _fire_fault_nearby[:2] if len(_fire_fault_nearby) >= 2 else _fire_fault_nearby
_cascade_hazard_names = ["合肥东部化工园", "庐阳化工仓储"]  # First 2 chem plants get anchored

hazards = []
hid = 1
_cascade_idx = 0  # track which cascade hazard we're placing
for htype, names in HAZARD_NAMES.items():
    for name in names:
        # P3: Anchor cascade-trigger hazards very close to fire stations near fault
        if name in _cascade_hazard_names and _cascade_idx < len(_anchor_fires):
            f_lat, f_lng = _anchor_fires[_cascade_idx]
            # Place hazard within 100-250m of fire station (well within buffer_radius=1200m)
            # Small offset ensures both are near the same blocked road
            clat = f_lat + rng.uniform(-0.0015, 0.0015)
            clng = f_lng + rng.uniform(-0.0015, 0.0015)
            risk = 3  # high risk for cascade demonstration
            _cascade_idx += 1
            print(f"    [CASCADE ANCHORED] {name} pinned at fire station ({f_lat:.4f},{f_lng:.4f})")
        elif htype == "化工厂":
            clat = rng.choice([rng.uniform(31.78, 31.95), rng.uniform(32.05, 32.15)])
            clng = rng.choice([rng.uniform(117.35, 117.55), rng.uniform(117.10, 117.25)])
        elif htype == "加油站":
            clat = rng.uniform(LAT_MIN + 0.02, LAT_MAX - 0.02)
            clng = rng.uniform(LNG_MIN + 0.02, LNG_MAX - 0.02)
        else:  # 燃气储罐
            clat = rng.uniform(31.70, 31.95)
            clng = rng.uniform(117.10, 117.40)
            risk = rng.integers(1, 4)

        if name not in _cascade_hazard_names:  # risk already set for anchored ones
            risk = rng.integers(1, 4)
        materials = ["液氨", "液化石油气", "丙烯腈", "苯乙烯", "氯气", "甲醇", "汽油", "柴油"]
        hazards.append({
            "id": hid, "name": name, "type": htype,
            "risk_level": risk,
            "hazard_material": rng.choice(materials),
            "buffer_radius": [500, 800, 1200][risk - 1],
            "lat": round(clat, 6), "lng": round(clng, 6),
        })
        hid += 1

hazard_gdf = gpd.GeoDataFrame(
    hazards,
    geometry=gpd.points_from_xy([h["lng"] for h in hazards], [h["lat"] for h in hazards]),
    crs="EPSG:4326",
)
hazard_gdf.to_file(DATA_DIR / "facilities_hazards.geojson", driver="GeoJSON")
print(f"  产出: facilities_hazards.geojson ({len(hazard_gdf)} 条)")
for _, r in hazard_gdf.iterrows():
    print(f"    [{r['type']}] {r['name']} 风险{r['risk_level']}级 半径{r['buffer_radius']}m")

# ── 2. 救援力量 (20个) ────────────────────────────────
print("\n--- 生成救援力量 ---")
RESCUE_NAMES = {
    "消防站": [f"合肥市消防救援支队特勤{'一二三四五六七八九十'[i]}站" for i in range(8)] +
              ["庐阳消防中队", "蜀山消防中队", "瑶海消防中队"],
    "物资储备库": ["合肥中央救灾物资库", "省红十字会备灾仓库", "肥东应急物资储备中心",
                  "肥西防汛物资仓库", "长丰应急储备库", "庐江救灾物资站",
                  "巢湖应急物资库", "包河区应急物资站", "蜀山医疗物资储备中心"],
}

_fire_coord_iter = iter(zip(_fire_lats, _fire_lngs))

rescue_list = []
rid = 1
for rtype, names in RESCUE_NAMES.items():
    for name in names:
        if rtype == "消防站":
            # Use pre-generated coordinates (consistent with hazard anchoring)
            clat, clng = next(_fire_coord_iter, (rng.uniform(31.75, 31.95), rng.uniform(117.15, 117.40)))
        else:
            clat = rng.uniform(LAT_MIN + 0.03, LAT_MAX - 0.03)
            clng = rng.uniform(LNG_MIN + 0.03, LNG_MAX - 0.03)

        capacity_val = rng.integers(8, 31) if rtype == "消防站" else rng.integers(50, 500)
        capacity_unit = "辆消防车" if rtype == "消防站" else "吨"
        coverage = rng.integers(3000, 8000) if rtype == "消防站" else rng.integers(5000, 15000)

        rescue_list.append({
            "id": rid, "name": name, "type": rtype,
            "capacity": capacity_val, "capacity_unit": capacity_unit,
            "coverage_radius": coverage,
            "lat": round(clat, 6), "lng": round(clng, 6),
        })
        rid += 1

rescue_gdf = gpd.GeoDataFrame(
    rescue_list,
    geometry=gpd.points_from_xy([r["lng"] for r in rescue_list], [r["lat"] for r in rescue_list]),
    crs="EPSG:4326",
)
rescue_gdf.to_file(DATA_DIR / "facilities_rescue.geojson", driver="GeoJSON")
print(f"  产出: facilities_rescue.geojson ({len(rescue_gdf)} 条)")
for _, r in rescue_gdf.iterrows():
    print(f"    [{r['type']}] {r['name']} 容量{r['capacity']}{r['capacity_unit']} 覆盖{r['coverage_radius']}m")

# ── 3. 避难缓冲 (10个) ──────────────────────────────────
print("\n--- 生成避难缓冲 ---")
SHELTER_NAMES = [
    ("合肥体育中心", "体育场"), ("天鹅湖公园", "公园"), ("逍遥津公园", "公园"),
    ("庐州公园", "公园"), ("少荃湖公园", "公园"), ("翡翠湖公园", "公园"),
    ("安徽省体育场", "体育场"), ("合肥奥体中心", "体育场"),
    ("滨湖会展中心", "会展中心"), ("北城运动公园", "公园"),
]

shelters = []
sid = 1
# 避难所按城市核心区分布
shelter_coords = [
    (31.820, 117.230),  # 体育中心
    (31.825, 117.220),  # 天鹅湖
    (31.868, 117.295),  # 逍遥津
    (31.895, 117.222),  # 庐州公园
    (31.935, 117.320),  # 少荃湖
    (31.770, 117.202),  # 翡翠湖
    (31.855, 117.285),  # 省体育场
    (31.740, 117.270),  # 奥体中心
    (31.720, 117.290),  # 会展中心
    (31.970, 117.235),  # 北城公园
]

for (name, stype), (clat, clng) in zip(SHELTER_NAMES, shelter_coords):
    # 加小随机扰动
    clat += rng.uniform(-0.005, 0.005)
    clng += rng.uniform(-0.005, 0.005)
    capacity_val = rng.integers(2000, 50000) if stype in ("体育场", "会展中心") else rng.integers(800, 8000)

    shelters.append({
        "id": sid, "name": name, "type": "避难所",
        "subtype": stype, "capacity": capacity_val,
        "lat": round(clat, 6), "lng": round(clng, 6),
    })
    sid += 1

shelter_gdf = gpd.GeoDataFrame(
    shelters,
    geometry=gpd.points_from_xy([s["lng"] for s in shelters], [s["lat"] for s in shelters]),
    crs="EPSG:4326",
)
shelter_gdf.to_file(DATA_DIR / "facilities_shelters.geojson", driver="GeoJSON")
print(f"  产出: facilities_shelters.geojson ({len(shelter_gdf)} 条)")
for _, r in shelter_gdf.iterrows():
    print(f"    [{r['subtype']}] {r['name']} 容量{r['capacity']}人")

print(f"\n=== Phase 1 数据生成完成 ===")
print(f"危险源: {len(hazard_gdf)} | 救援力量: {len(rescue_gdf)} | 避难所: {len(shelter_gdf)}")
print(f"文件位置: {DATA_DIR}")
