"""
为 grid_base.geojson 补充人口和 GDP 属性
基于合肥实际统计数据的合理模拟分配（500m 网格）

合肥市 2024 年数据（近似）:
- 常住人口: ~963 万
- GDP: ~1.27 万亿 → 人均 GDP ~13.2 万

密度分档:
- 核心城区 (瑶海/庐阳/蜀山/包河): 8000 人/km²
- 近郊区 (长丰/肥东/肥西): 1200 人/km²
- 远郊区 (庐江/巢湖): 400 人/km²

500m × 500m 网格 = 0.25 km²
"""
import os
from pathlib import Path

LIB = Path("F:/anaconda/envs/zhenmai/Library/share")
os.environ.setdefault("GDAL_DATA", str(LIB / "gdal"))
os.environ.setdefault("PROJ_LIB", str(LIB / "proj"))

import numpy as np
import geopandas as gpd

DATA_DIR = Path(__file__).resolve().parent.parent / "数据文件"
GRID_FILE = DATA_DIR / "grid_base.geojson"
GRID_AREA_KM2 = 0.25  # 500m × 500m
SEED = 42

rng = np.random.default_rng(SEED)

# ── 区县人口密度 (人/km²) 和人均GDP (万元/年) ──────────────
DISTRICT_CONFIG = {
    "瑶海区": {"pop_density": 6000, "gdp_per_capita": 10.0},
    "庐阳区": {"pop_density": 5000, "gdp_per_capita": 12.5},
    "蜀山区": {"pop_density": 2900, "gdp_per_capita": 14.0},
    "包河区": {"pop_density": 4000, "gdp_per_capita": 13.0},
    "长丰县": {"pop_density": 440,  "gdp_per_capita": 8.0},
    "肥东县": {"pop_density": 410,  "gdp_per_capita": 9.0},
    "肥西县": {"pop_density": 470,  "gdp_per_capita": 11.0},
    "庐江县": {"pop_density": 425,  "gdp_per_capita": 5.5},
    "巢湖市": {"pop_density": 390,  "gdp_per_capita": 6.0},
}

print("Loading grid_base.geojson ...")
grid = gpd.read_file(GRID_FILE)
print(f"  Grids: {len(grid)}")
print(f"  Districts: {grid['district'].value_counts().to_dict()}")

# ── 分配人口和 GDP ───────────────────────────────────────
populations = []
gdps = []

for _, row in grid.iterrows():
    district = row["district"]
    cfg = DISTRICT_CONFIG.get(district, {"pop_density": 500, "gdp_per_capita": 5.0})

    # 基础人口 = 密度 × 网格面积
    base_pop = cfg["pop_density"] * GRID_AREA_KM2
    # 加 ±30% 随机扰动模拟空间异质性
    pop = base_pop * rng.uniform(0.7, 1.3)
    pop = max(pop, 0.1)  # 最少 0.1 人（郊野地块）
    populations.append(round(pop, 2))

    # GDP = 人均GDP × 人口，加 ±20% 扰动
    base_gdp = pop * cfg["gdp_per_capita"]
    gdp = base_gdp * rng.uniform(0.8, 1.2)
    gdps.append(round(gdp, 2))

grid["population"] = populations
grid["gdp"] = gdps  # 单位: 万元

# ── 验证汇总 ────────────────────────────────────────────
total_pop = grid["population"].sum()
total_gdp = grid["gdp"].sum()
print(f"\nSummary:")
print(f"  Total pop: {total_pop:,.0f} ({total_pop/10000:.1f}wan)")
print(f"  Total GDP: {total_gdp:,.0f} wan ({total_gdp/10000:.1f} yi)")
print(f"\nDistrict summary:")
for d in grid["district"].unique():
    sub = grid[grid["district"] == d]
    n = len(sub)
    pop = sub['population'].sum()
    gdp = sub['gdp'].sum()
    dens = pop / (n * GRID_AREA_KM2)
    print(f"  {d}: pop={pop:,.0f}, gdp={gdp:,.0f}wan, grids={n}, density={dens:.0f}/km2")

# ── 保存 ────────────────────────────────────────────────
print(f"\n保存到 {GRID_FILE} ...")
grid.to_file(GRID_FILE, driver="GeoJSON")
print("完成！grid_base.geojson 已补充 population 和 gdp 字段。")
