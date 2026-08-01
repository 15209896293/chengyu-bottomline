"""
step25_export_lite.py — 前端精简路网导出（lite GeoJSON）

road_blocked 全量 58K 段（~23MB）不适合前端加载，生成精简版：
  - 受影响路段（非正常）全部保留
  - 正常路段按比例抽样（保持空间分布），总段数控制在 ~3000
输出到 dashboard/public/data/geo/（前端地图数据源）

同时更新 hefei_roads_lite.geojson（基准路网精简，与当前 OSM 一致）。
"""
import json
import sys
from pathlib import Path

import geopandas as gpd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config_loader import get_config

cfg = get_config()
DATA_DIR = Path(__file__).resolve().parent.parent / "数据文件"
GEO_DIR = Path(__file__).resolve().parent.parent / "dashboard" / "public" / "data" / "geo"

MAGNITUDES = [5.0, 5.5, 6.0, 6.5, 7.0, 7.5]
TARGET_TOTAL = 3000  # 与旧 lite 版规模一致
SAMPLE_SEED = 42


def export_lite(source_path, out_path, target_total=TARGET_TOTAL):
    gdf = gpd.read_file(source_path)
    total = len(gdf)
    if total <= target_total:
        gdf.to_file(out_path, driver="GeoJSON")
        return total, total

    # 分层抽样：按 block_level 分层，各层按比例抽到 target_total
    levels = ["完全阻断", "严重损伤", "轻度损伤", "正常"]
    pieces = []
    for lv in levels:
        sub = gdf[gdf["block_level"] == lv]
        if len(sub) == 0:
            continue
        # 受影响层优先保权重，正常层少量抽样
        n_target = int(target_total * len(sub) / total)
        n_target = max(1, min(n_target, len(sub)))
        pieces.append(sub.sample(n=n_target, random_state=SAMPLE_SEED))
    lite = gpd.GeoDataFrame(gpd.pd.concat(pieces, ignore_index=True), crs=gdf.crs)
    # 若不足 target_total（如某层为0），从剩余正常段补足
    if len(lite) < target_total:
        need = target_total - len(lite)
        remaining = gdf.loc[~gdf.index.isin(lite.index)]
        if len(remaining) > 0:
            lite = gpd.GeoDataFrame(
                gpd.pd.concat([lite, remaining.sample(n=min(need, len(remaining)), random_state=SAMPLE_SEED)],
                              ignore_index=True),
                crs=gdf.crs,
            )
    lite.to_file(out_path, driver="GeoJSON")
    return total, len(lite)


def main():
    print("=" * 60)
    print("前端精简路网导出（lite）")
    print("=" * 60)

    # 基准路网 lite（全震级共用底图）
    roads = gpd.read_file(DATA_DIR / "hefei_roads_osm.geojson")
    roads_lite = roads.sample(
        n=min(12000, len(roads)), random_state=SAMPLE_SEED)
    roads_lite.to_file(GEO_DIR / "hefei_roads_lite.geojson", driver="GeoJSON")
    print(f"hefei_roads_lite: {len(roads)} → {len(roads_lite)}")

    for mag in MAGNITUDES:
        src = DATA_DIR / f"road_blocked_M{mag:.1f}.geojson"
        out = GEO_DIR / f"road_blocked_M{mag:.1f}_lite.geojson"
        n_src, n_lite = export_lite(src, out)
        print(f"M{mag:.1f}: {n_src} → {n_lite} 段")

    print("\n[OK] lite 导出完成")


if __name__ == "__main__":
    main()
