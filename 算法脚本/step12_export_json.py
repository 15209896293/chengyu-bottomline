"""
step12_export_json.py — 前端大屏JSON数据导出

将所有CSV和GeoJSON数据转换为前端可直接加载的JSON结构。
对每个震级 M{X}（5.0~7.5）生成 dashboard_M{X}.json，为前端大屏提供数据源。

数据量控制策略：
  1. 网格数据：按烈度区间分组采样，每组最多200个代表点
  2. 路网数据：只保留"完全阻断"和"严重损伤"路段，仅输出起止点坐标
  3. 医院/设施数据：全部保留（数据量小）
  4. 图表数据：汇总后输出
"""
import os
from pathlib import Path

# ── GDAL/PROJ 路径（必须在导入 geopandas 前设置）──
LIB = Path("F:/anaconda/envs/zhenmai/Library/share")
os.environ.setdefault("GDAL_DATA", str(LIB / "gdal"))
os.environ.setdefault("PROJ_LIB", str(LIB / "proj"))

import warnings
warnings.filterwarnings("ignore")

import json
import random
from datetime import datetime

import numpy as np
import pandas as pd
import geopandas as gpd

# ═══════════════════════════════════════════════════════════
# 全局配置
# ═══════════════════════════════════════════════════════════
SEED = 42
np.random.seed(SEED)
random.seed(SEED)

DATA_DIR = Path(__file__).resolve().parent.parent / "数据文件"
MAGNITUDES = [5.0, 5.5, 6.0, 6.5, 7.0, 7.5]
CSV_ENCODING = "utf-8-sig"

# 采样参数
MAX_GRID_SAMPLES = 200          # 每个烈度区间最多采样网格数
MAX_ROADS = 5000                # 输出最大阻断路段数
INTENSITY_BINS = [              # 烈度区间分组
    (0, 3), (3, 5), (5, 6), (6, 7), (7, 8), (8, float("inf")),
]

# 震中坐标（断裂带质心，与 step4 一致）
EPICENTER_FALLBACK = {"lng": 117.28, "lat": 31.82}

# 布尔列
BOOL_COLS_COLLAPSE = [
    "medical_collapse", "rescue_collapse",
    "transport_collapse", "shelter_collapse", "city_collapse",
]


# ═══════════════════════════════════════════════════════════
# 静态数据加载
# ═══════════════════════════════════════════════════════════
def compute_epicenter():
    """从断裂带质心计算震中坐标，失败则用默认值。"""
    try:
        fault = gpd.read_file(DATA_DIR / "tanlu_fault_hefei_4490.geojson")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            centroid = fault.geometry.centroid.iloc[0]
        return {"lng": round(float(centroid.x), 4), "lat": round(float(centroid.y), 4)}
    except Exception:
        return dict(EPICENTER_FALLBACK)


def _to_bool_series(s):
    """将列安全转为布尔。"""
    return s.astype(str).str.strip().str.lower().isin(["true", "1", "yes"])


def load_static_data():
    """加载不随震级变化的静态数据。"""
    static = {}

    # 医院基础数据
    static["hospitals"] = pd.read_csv(
        DATA_DIR / "hefei_hospital.csv", encoding=CSV_ENCODING
    )

    # 设施 GeoJSON
    static["hazards_gdf"] = gpd.read_file(DATA_DIR / "facilities_hazards.geojson")
    static["rescue_gdf"] = gpd.read_file(DATA_DIR / "facilities_rescue.geojson")
    static["shelters_gdf"] = gpd.read_file(DATA_DIR / "facilities_shelters.geojson")

    # 区县边界（简化几何以减小体积）
    districts_gdf = gpd.read_file(DATA_DIR / "hefei_districts_4490.geojson")
    districts_gdf["geometry"] = districts_gdf.geometry.simplify(tolerance=0.005)
    static["districts_geojson"] = json.loads(districts_gdf.to_json())

    # 断裂带
    fault_gdf = gpd.read_file(DATA_DIR / "tanlu_fault_hefei_4490.geojson")
    static["fault_geojson"] = json.loads(fault_gdf.to_json())

    # 网格基础数据（预计算质心）
    grid_gdf = gpd.read_file(DATA_DIR / "grid_base.geojson")
    bounds = grid_gdf.geometry.bounds
    grid_gdf["lng"] = ((bounds["minx"] + bounds["maxx"]) / 2).round(6)
    grid_gdf["lat"] = ((bounds["miny"] + bounds["maxy"]) / 2).round(6)
    static["grid_df"] = grid_gdf[["cell_id", "district", "lng", "lat"]].copy()

    # 崩溃临界点
    collapse_path = DATA_DIR / "collapse_threshold.csv"
    if collapse_path.exists():
        df = pd.read_csv(collapse_path, encoding=CSV_ENCODING)
        df["magnitude"] = df["magnitude"].astype(float)
        for col in BOOL_COLS_COLLAPSE:
            if col in df.columns:
                df[col] = _to_bool_series(df[col])
        static["collapse_df"] = df
    else:
        static["collapse_df"] = None

    # 韧性汇总
    resilience_path = DATA_DIR / "resilience_summary.csv"
    if resilience_path.exists():
        df = pd.read_csv(resilience_path, encoding=CSV_ENCODING)
        df["magnitude"] = df["magnitude"].astype(float)
        if "city_collapse" in df.columns:
            df["city_collapse"] = _to_bool_series(df["city_collapse"])
        static["resilience_df"] = df
    else:
        static["resilience_df"] = None

    # 防治策略
    strategy_path = DATA_DIR / "prevention_strategy.csv"
    if strategy_path.exists():
        static["strategy_df"] = pd.read_csv(strategy_path, encoding=CSV_ENCODING)
    else:
        static["strategy_df"] = None

    return static


def precompute_magnitude_curve(static):
    """预计算全震级趋势曲线（每个JSON都包含完整曲线）。"""
    curve = []
    for mag in MAGNITUDES:
        loss_df = pd.read_csv(
            DATA_DIR / f"loss_estimate_M{mag:.1f}.csv", encoding=CSV_ENCODING
        )
        loss = round(float(loss_df["economic_loss"].sum()), 2)
        exposed_pop = int(loss_df["exposed_population"].sum())

        resilience = None
        if static["resilience_df"] is not None:
            row = static["resilience_df"][static["resilience_df"]["magnitude"] == mag]
            if len(row) > 0:
                resilience = round(float(row.iloc[0]["resilience_index"]), 4)

        curve.append({
            "magnitude": mag,
            "loss": loss,
            "exposed_pop": exposed_pop,
            "resilience": resilience,
        })
    return curve


def get_threshold_magnitude(static):
    """获取城市崩溃临界震级（首次崩溃的震级）。"""
    if static["collapse_df"] is not None:
        df = static["collapse_df"]
        collapsed = df[df["city_collapse"]]["magnitude"].tolist()
        if collapsed:
            return min(collapsed)
    elif static["resilience_df"] is not None:
        df = static["resilience_df"]
        collapsed = df[df["city_collapse"]]["magnitude"].tolist()
        if collapsed:
            return min(collapsed)
    return None


# ═══════════════════════════════════════════════════════════
# KPI 构建
# ═══════════════════════════════════════════════════════════
def build_kpi(mag, static, road_gdf):
    """构建KPI指标。"""
    # 损失估算
    loss_df = pd.read_csv(
        DATA_DIR / f"loss_estimate_M{mag:.1f}.csv", encoding=CSV_ENCODING
    )
    total_pop = int(loss_df["total_population"].sum())
    exposed_pop = int(loss_df["exposed_population"].sum())
    affected_pop = int(loss_df["affected_population"].sum())
    total_gdp = round(float(loss_df["total_gdp"].sum()), 2)
    economic_loss = round(float(loss_df["economic_loss"].sum()), 2)

    # 医院可达性
    acc_df = pd.read_csv(
        DATA_DIR / f"accessibility_M{mag:.1f}.csv", encoding=CSV_ENCODING
    )
    total_hospitals = len(acc_df)
    vc = acc_df["accessibility"].value_counts()
    accessible = int(vc.get("正常可达", 0) + vc.get("可达但受限", 0))
    inaccessible = int(vc.get("不可达", 0))

    # 道路阻断率
    total_roads = len(road_gdf)
    blocked_count = int(road_gdf["block_level"].isin(["完全阻断", "严重损伤"]).sum())
    road_block_rate = round(blocked_count / total_roads, 4) if total_roads > 0 else 0.0

    # 城市崩溃
    city_collapse = False
    if static["collapse_df"] is not None:
        row = static["collapse_df"][static["collapse_df"]["magnitude"] == mag]
        if len(row) > 0:
            city_collapse = bool(row.iloc[0]["city_collapse"])
    elif static["resilience_df"] is not None:
        row = static["resilience_df"][static["resilience_df"]["magnitude"] == mag]
        if len(row) > 0:
            city_collapse = bool(row.iloc[0]["city_collapse"])

    return {
        "total_population": total_pop,
        "exposed_population": exposed_pop,
        "affected_population": affected_pop,
        "total_gdp_yi": total_gdp,
        "economic_loss_yi": economic_loss,
        "total_hospitals": total_hospitals,
        "accessible_hospitals": accessible,
        "inaccessible_hospitals": inaccessible,
        "road_block_rate": road_block_rate,
        "city_collapse": city_collapse,
    }


# ═══════════════════════════════════════════════════════════
# 地图图层构建
# ═══════════════════════════════════════════════════════════
def build_intensity_grid(mag, static):
    """构建烈度网格数据（按烈度区间采样）。"""
    intensity_df = pd.read_csv(
        DATA_DIR / f"grid_intensity_M{mag:.1f}.csv", encoding=CSV_ENCODING
    )
    grid = static["grid_df"].merge(
        intensity_df[["cell_id", "intensity"]], on="cell_id", how="inner"
    )

    samples = []
    for low, high in INTENSITY_BINS:
        mask = (grid["intensity"] >= low) & (grid["intensity"] < high)
        group = grid[mask]
        n = min(len(group), MAX_GRID_SAMPLES)
        if n == 0:
            continue
        sampled = group.sample(n=n, random_state=SEED)
        for _, row in sampled.iterrows():
            samples.append({
                "cell_id": int(row["cell_id"]),
                "intensity": round(float(row["intensity"]), 2),
                "district": str(row["district"]),
                "lng": float(row["lng"]),
                "lat": float(row["lat"]),
            })
    return samples


def build_hospitals(mag, static):
    """构建医院图层（全部保留）。

    使用行索引匹配可达性，避免重名医院合并产生重复行。
    """
    acc_df = pd.read_csv(
        DATA_DIR / f"accessibility_M{mag:.1f}.csv", encoding=CSV_ENCODING
    )
    hospitals = static["hospitals"].copy()
    hospitals["_idx"] = range(len(hospitals))
    acc_df = acc_df.copy()
    acc_df["_idx"] = range(len(acc_df))
    merged = hospitals.merge(
        acc_df[["_idx", "accessibility", "district"]], on="_idx", how="left"
    )
    result = []
    for _, row in merged.iterrows():
        result.append({
            "name": str(row["name"]),
            "lng": round(float(row["lng"]), 6),
            "lat": round(float(row["lat"]), 6),
            "district": str(row.get("district", "")),
            "accessibility": str(row.get("accessibility", "未知")),
        })
    return result


def build_roads_blocked(road_gdf):
    """构建阻断道路图层（仅完全阻断+严重损伤，仅起止点）。"""
    blocked = road_gdf[road_gdf["block_level"].isin(["完全阻断", "严重损伤"])].copy()
    if len(blocked) > MAX_ROADS:
        blocked = blocked.sample(n=MAX_ROADS, random_state=SEED)

    result = []
    for _, row in blocked.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        coords = list(geom.coords)
        if len(coords) < 1:
            continue
        start = coords[0]
        end = coords[-1]
        result.append({
            "road_id": int(row["road_id"]),
            "block_level": str(row["block_level"]),
            "lng_start": round(float(start[0]), 6),
            "lat_start": round(float(start[1]), 6),
            "lng_end": round(float(end[0]), 6),
            "lat_end": round(float(end[1]), 6),
        })
    return result


def build_facilities(mag, static):
    """构建设施图层（全部保留，关联可达性）。"""
    acc_df = pd.read_csv(
        DATA_DIR / f"accessibility_facilities_M{mag:.1f}.csv", encoding=CSV_ENCODING
    )
    # 按类型建立 name → accessibility 查找表
    acc_lookup = {}
    for _, row in acc_df.iterrows():
        key = (row["type"], row["name"])
        if key not in acc_lookup:
            acc_lookup[key] = row["accessibility"]

    def _build_list(gdf, csv_type, include_capacity=False):
        items = []
        for _, row in gdf.iterrows():
            item = {
                "name": str(row["name"]),
                "lng": round(float(row["lng"]), 6),
                "lat": round(float(row["lat"]), 6),
                "accessibility": str(acc_lookup.get((csv_type, row["name"]), "未知")),
            }
            if include_capacity and "capacity" in gdf.columns:
                try:
                    item["capacity"] = int(row["capacity"])
                except (ValueError, TypeError):
                    item["capacity"] = 0
            items.append(item)
        return items

    return {
        "hazards": _build_list(static["hazards_gdf"], "危险源"),
        "rescue": _build_list(static["rescue_gdf"], "消防站"),
        "shelters": _build_list(static["shelters_gdf"], "避难所", include_capacity=True),
    }


# ═══════════════════════════════════════════════════════════
# 图表数据构建
# ═══════════════════════════════════════════════════════════
def build_charts(mag, static, magnitude_curve):
    """构建图表数据。"""
    loss_df = pd.read_csv(
        DATA_DIR / f"loss_estimate_M{mag:.1f}.csv", encoding=CSV_ENCODING
    )

    # 1. 区县损失柱状图
    district_loss = []
    for _, row in loss_df.iterrows():
        district_loss.append({
            "district": str(row["district"]),
            "population": int(row["total_population"]),
            "exposed": int(row["exposed_population"]),
            "loss": round(float(row["economic_loss"]), 2),
            "intensity": round(float(row["avg_intensity"]), 2),
        })

    # 2. 可达性分布
    acc_hosp = pd.read_csv(
        DATA_DIR / f"accessibility_M{mag:.1f}.csv", encoding=CSV_ENCODING
    )
    hosp_dist = {"正常可达": 0, "可达但受限": 0, "不可达": 0}
    for k, v in acc_hosp["accessibility"].value_counts().items():
        if k in hosp_dist:
            hosp_dist[k] = int(v)

    acc_fac = pd.read_csv(
        DATA_DIR / f"accessibility_facilities_M{mag:.1f}.csv", encoding=CSV_ENCODING
    )
    fac_dist = {}
    for fac_type in ["消防站", "危险源", "避难所"]:
        subset = acc_fac[acc_fac["type"] == fac_type]
        dist = {"正常可达": 0, "可达但受限": 0, "不可达": 0}
        for k, v in subset["accessibility"].value_counts().items():
            if k in dist:
                dist[k] = int(v)
        fac_dist[fac_type] = dist

    # 3. 空间失配（风险-经济暴露错配）
    spatial_mismatch = []
    for _, row in loss_df.iterrows():
        risk_score = round(float(row["avg_intensity"]) / 10.0, 2)
        spatial_mismatch.append({
            "district": str(row["district"]),
            "risk_score": risk_score,
            "gdp": round(float(row["total_gdp"]), 2),
            "population": int(row["total_population"]),
        })

    # 4. 全震级趋势曲线（预计算）
    # 5. 崩溃临界点
    threshold_mag = get_threshold_magnitude(static)
    collapse = _build_collapse(mag, static, threshold_mag)

    # 6. 韧性指数
    resilience = _build_resilience(mag, static)

    return {
        "district_loss": district_loss,
        "accessibility_distribution": {
            "hospitals": hosp_dist,
            "facilities": fac_dist,
        },
        "spatial_mismatch": spatial_mismatch,
        "magnitude_curve": magnitude_curve,
        "collapse": collapse,
        "resilience": resilience,
    }


def _build_collapse(mag, static, threshold_mag):
    """构建崩溃临界点数据。"""
    empty = {
        "medical_ratio": 0.0, "rescue_ratio": 0.0,
        "transport_ratio": 0.0, "shelter_ratio": 0.0,
        "medical_collapse": False, "rescue_collapse": False,
        "transport_collapse": False, "shelter_collapse": False,
        "city_collapse": False, "threshold_magnitude": threshold_mag,
    }
    if static["collapse_df"] is None:
        return empty

    row = static["collapse_df"][static["collapse_df"]["magnitude"] == mag]
    if len(row) == 0:
        return empty
    r = row.iloc[0]
    return {
        "medical_ratio": round(float(r["medical_ratio"]), 4),
        "rescue_ratio": round(float(r["rescue_ratio"]), 4),
        "transport_ratio": round(float(r["transport_ratio"]), 4),
        "shelter_ratio": round(float(r["shelter_ratio"]), 4),
        "medical_collapse": bool(r["medical_collapse"]),
        "rescue_collapse": bool(r["rescue_collapse"]),
        "transport_collapse": bool(r["transport_collapse"]),
        "shelter_collapse": bool(r["shelter_collapse"]),
        "city_collapse": bool(r["city_collapse"]),
        "threshold_magnitude": threshold_mag,
    }


def _build_resilience(mag, static):
    """构建韧性指数数据。"""
    empty = {
        "medical": 0.0, "shelter": 0.0, "transport": 0.0,
        "safety": 0.0, "resilience_index": 0.0,
    }
    if static["resilience_df"] is None:
        return empty

    row = static["resilience_df"][static["resilience_df"]["magnitude"] == mag]
    if len(row) == 0:
        return empty
    r = row.iloc[0]
    return {
        "medical": round(float(r["medical"]), 4),
        "shelter": round(float(r["shelter"]), 4),
        "transport": round(float(r["transport"]), 4),
        "safety": round(float(r["safety"]), 4),
        "resilience_index": round(float(r["resilience_index"]), 4),
    }


# ═══════════════════════════════════════════════════════════
# 防治策略
# ═══════════════════════════════════════════════════════════
def build_prevention(static):
    """构建防治策略数据。"""
    if static["strategy_df"] is None:
        return {"strategies": []}

    strategies = []
    for _, row in static["strategy_df"].iterrows():
        strategies.append({
            "strategy": str(row.get("strategy", "")),
            "description": str(row.get("description", "")),
            "key_roads_repaired": int(row.get("key_roads_repaired", 0)),
            "temp_medical_points_added": int(row.get("temp_medical_points_added", 0)),
            "medical_ratio_before": round(float(row.get("medical_ratio_before", 0)), 4),
            "medical_ratio_after": round(float(row.get("medical_ratio_after", 0)), 4),
            "rescue_ratio_before": round(float(row.get("rescue_ratio_before", 0)), 4),
            "rescue_ratio_after": round(float(row.get("rescue_ratio_after", 0)), 4),
            "city_collapse_before": bool(row.get("city_collapse_before", False)),
            "city_collapse_after": bool(row.get("city_collapse_after", False)),
            "threshold_shift": str(row.get("threshold_shift", "")),
        })
    return {"strategies": strategies}


# ═══════════════════════════════════════════════════════════
# JSON 组装与保存
# ═══════════════════════════════════════════════════════════
def build_dashboard(mag, static, epicenter, magnitude_curve, generate_time):
    """构建单个震级的完整JSON结构。"""
    # 加载路网数据（该震级独有）
    road_gdf = gpd.read_file(DATA_DIR / f"road_blocked_M{mag:.1f}.geojson")

    return {
        "meta": {
            "magnitude": mag,
            "epicenter": epicenter,
            "generate_time": generate_time,
        },
        "kpi": build_kpi(mag, static, road_gdf),
        "map_layers": {
            "intensity_grid": build_intensity_grid(mag, static),
            "hospitals": build_hospitals(mag, static),
            "roads_blocked": build_roads_blocked(road_gdf),
            "facilities": build_facilities(mag, static),
            "districts": static["districts_geojson"],
            "fault": static["fault_geojson"],
        },
        "charts": build_charts(mag, static, magnitude_curve),
        "prevention": build_prevention(static),
    }


def save_json(data, mag):
    """保存JSON文件。"""
    out_path = DATA_DIR / f"dashboard_M{mag:.1f}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return out_path


# ═══════════════════════════════════════════════════════════
# 验证
# ═══════════════════════════════════════════════════════════
def verify(magnitudes):
    """验证输出正确性，失败则打印原因。"""
    ok = True
    reasons = []

    for mag in magnitudes:
        tag = f"M{mag:.1f}"
        path = DATA_DIR / f"dashboard_M{mag:.1f}.json"

        # 1. 文件存在
        if not path.exists():
            ok = False
            reasons.append(f"{tag}: 文件不存在")
            continue

        # 2. JSON可解析
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            ok = False
            reasons.append(f"{tag}: JSON解析失败 - {e}")
            continue

        # 3. KPI与CSV一致（抽样检查）
        loss_df = pd.read_csv(
            DATA_DIR / f"loss_estimate_M{mag:.1f}.csv", encoding=CSV_ENCODING
        )
        expected_loss = round(float(loss_df["economic_loss"].sum()), 2)
        actual_loss = data["kpi"]["economic_loss_yi"]
        if abs(actual_loss - expected_loss) > 0.1:
            ok = False
            reasons.append(
                f"{tag}: 经济损失不一致 (JSON={actual_loss}, CSV={expected_loss})"
            )

        expected_pop = int(loss_df["total_population"].sum())
        actual_pop = data["kpi"]["total_population"]
        if actual_pop != expected_pop:
            ok = False
            reasons.append(
                f"{tag}: 总人口不一致 (JSON={actual_pop}, CSV={expected_pop})"
            )

        # 4. 文件大小 < 5MB
        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb >= 5.0:
            ok = False
            reasons.append(f"{tag}: 文件大小 {size_mb:.2f}MB >= 5MB")

        # 5. 结构完整性
        required_keys = {"meta", "kpi", "map_layers", "charts", "prevention"}
        missing = required_keys - set(data.keys())
        if missing:
            ok = False
            reasons.append(f"{tag}: 缺少顶层字段 {missing}")

        size_str = f"{size_mb:.2f}MB"
        checks = []
        if abs(actual_loss - expected_loss) <= 0.1:
            checks.append("KPI一致")
        if size_mb < 5.0:
            checks.append("大小合格")
        checks.append("JSON可解析")
        print(f"  {tag}: {size_str}  [{'/'.join(checks)}]")

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
    print("step12 前端大屏JSON数据导出")
    print("=" * 60)

    # 震中
    epicenter = compute_epicenter()
    print(f"  震中: ({epicenter['lng']}, {epicenter['lat']})")

    generate_time = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    print(f"  生成时间: {generate_time}")

    # 加载静态数据
    print("\n加载静态数据 ...")
    static = load_static_data()
    print(f"  医院: {len(static['hospitals'])} 个")
    print(f"  危险源: {len(static['hazards_gdf'])} 个")
    print(f"  消防站: {len(static['rescue_gdf'])} 个")
    print(f"  避难所: {len(static['shelters_gdf'])} 个")
    print(f"  网格: {len(static['grid_df'])} 个")
    print(f"  崩溃阈值: {'已加载' if static['collapse_df'] is not None else '不存在'}")
    print(f"  韧性汇总: {'已加载' if static['resilience_df'] is not None else '不存在'}")
    print(f"  防治策略: {'已加载' if static['strategy_df'] is not None else '不存在(输出空数组)'}")

    # 预计算趋势曲线
    print("\n预计算全震级趋势曲线 ...")
    magnitude_curve = precompute_magnitude_curve(static)
    for item in magnitude_curve:
        print(f"  M{item['magnitude']:.1f}: 损失={item['loss']}亿  "
              f"暴露={item['exposed_pop']}  韧性={item['resilience']}")

    # 逐震级生成JSON
    print(f"\n{'─' * 60}")
    print("逐震级生成JSON ...")
    print(f"{'─' * 60}")

    for mag in MAGNITUDES:
        print(f"\n■ M{mag:.1f}")
        try:
            dashboard = build_dashboard(
                mag, static, epicenter, magnitude_curve, generate_time
            )
            out_path = save_json(dashboard, mag)
            size_mb = out_path.stat().st_size / (1024 * 1024)
            print(f"  KPI: 损失={dashboard['kpi']['economic_loss_yi']}亿  "
                  f"暴露={dashboard['kpi']['exposed_population']}  "
                  f"崩溃={dashboard['kpi']['city_collapse']}")
            print(f"  网格采样: {len(dashboard['map_layers']['intensity_grid'])} 个")
            print(f"  阻断路段: {len(dashboard['map_layers']['roads_blocked'])} 条")
            print(f"  保存: {out_path.name} ({size_mb:.2f}MB)")
        except Exception as e:
            import traceback
            print(f"  [错误] {e}")
            traceback.print_exc()

    # 验证
    print(f"\n{'─' * 60}")
    print("验证输出 ...")
    verify(MAGNITUDES)

    print(f"\n{'=' * 60}")
    print("完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
