"""
step22_vulnerable_facilities.py — 脆弱群体设施采集（底线债务叙事的补强）

采集学校（中小学/幼儿园）、养老院、福利院等"脆弱群体设施"POI，
计算其在 M6.0 烈度场下的暴露度（位于高烈度区的脆弱设施数量/占比），
输出 数据文件/vulnerable_facilities.geojson + vulnerable_exposure_summary.csv。

数据源：高德地图 Web 服务 API（与 crawl_real_facilities.py 同通道）。
注意：高德每日配额有限，配额超限时优雅降级（仅记录，不中断流程）；
配额恢复后重跑本脚本即可补全数据。

用法：python step22_vulnerable_facilities.py
"""
import os
import time
import json
from datetime import datetime
from pathlib import Path
import warnings
warnings.filterwarnings("ignore")

LIB = Path("F:/anaconda/envs/zhenmai/Library/share")
os.environ.setdefault("GDAL_DATA", str(LIB / "gdal"))
os.environ.setdefault("PROJ_LIB", str(LIB / "proj"))

import requests
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point

DATA_DIR = Path(__file__).resolve().parent.parent / "数据文件"
AMAP_KEY = "6b7b1ccf00f53270619fa4f84b8fc0e7"

# 脆弱群体设施采集配置（高德 POI 分类/关键词）
FACILITY_TYPES = [
    # (名称, 高德 types, 关键词回退)
    ("小学", "141201", "小学"),
    ("中学", "141202", "中学"),
    ("幼儿园", "141204", "幼儿园"),
    ("养老院", "", "养老院"),
    ("福利院", "", "福利院"),
    # 承灾基础设施（电力/供水）
    ("供电设施", "", "供电"),
    ("变电站", "", "变电站"),
    ("水厂", "", "自来水"),
]


def fetch_poi(keyword, poi_type, page=1, city="合肥", retries=2):
    """调用高德 /place/text 接口（含重试与配额识别）。"""
    url = "https://restapi.amap.com/v3/place/text"
    params = {
        "key": AMAP_KEY,
        "keywords": keyword,
        "types": poi_type,
        "city": city,
        "offset": 20,
        "page": page,
        "extensions": "base",
    }
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()
            if data.get("status") != "1":
                info = data.get("info", "")
                if "LIMIT" in info:
                    return None, 0, info  # 配额超限
                return [], 0, info
            return data.get("pois", []), int(data.get("count", 0)), None
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(1.0)
            else:
                return [], 0, str(e)
    return [], 0, None


def collect_all():
    """采集全部脆弱设施 POI。返回 (记录列表, 失败信息)。"""
    records = []
    quota_failed = []
    for name, ptype, kw in FACILITY_TYPES:
        pois, total, err = fetch_poi(kw, ptype)
        if pois is None:
            quota_failed.append(f"{name}: {err}")
            continue
        if err:
            quota_failed.append(f"{name}: {err}")
            continue
        # 分页拉全（按 count 循环，去重防重）
        page = 1
        seen = set()
        while len(pois) < total and pois:
            more, _, err2 = fetch_poi(kw, ptype, page=page + 1)
            if err2 or more is None or not more:
                break
            pois.extend(more)
            page += 1
            if page > 40:  # 安全上限
                break
        # 去重（按 name+location）
        dedup = {}
        for p in pois:
            dedup.setdefault((p.get("name", ""), p.get("location", "")), p)
        pois = list(dedup.values())
        for p in pois:
            try:
                loc = p.get("location", "").split(",")
                if len(loc) != 2:
                    continue
                records.append({
                    "name": p.get("name", ""),
                    "type": name,
                    "lon": float(loc[0]),
                    "lat": float(loc[1]),
                    "address": p.get("address", ""),
                    "adcode": p.get("adcode", ""),
                })
            except (ValueError, TypeError):
                continue
        print(f"  {name}: {total} 个")
        time.sleep(0.5)  # 高德 QPS 限制
    return records, quota_failed


def compute_exposure(records, mag=6.0):
    """计算脆弱设施在 M{mag} 烈度场下的暴露度。"""
    if not records:
        return None
    import numpy as np
    from intensity_model import IntensityModel
    from config_loader import get_config

    imodel = IntensityModel()
    cfg = get_config()
    params = cfg.get("intensity", "yu2013", default={})
    c1, c2, c3, c4, c5 = (params.get(k, d) for k, d in
                          [("c1", 1.785), ("c2", 1.352), ("c3", 1.038),
                           ("c4", 0.017), ("c5", 0.494)])

    # 断裂带质心震中
    EPI = (117.28, 31.82)
    R = 6371.0

    def haversine(lon, lat):
        lon1, lat1, lon2, lat2 = map(np.radians, [EPI[0], EPI[1], lon, lat])
        a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
        return 2 * R * np.arcsin(np.sqrt(a))

    summary = []
    for rec in records:
        d = haversine(rec["lon"], rec["lat"])
        R_sat = max(d, 0.1) + c4 * np.exp(c5 * mag)
        rec["intensity"] = round(float(c1 + c2 * mag - c3 * np.log(R_sat)), 2)
        rec["grade"] = "VIII+" if rec["intensity"] >= 7.0 else ("VI-VII" if rec["intensity"] >= 6.0 else "≤V")

    df = pd.DataFrame(records)
    df["high_exposure"] = df["intensity"] >= 7.0
    by_type = df.groupby("type").agg(
        count=("name", "count"),
        high_exposure=("high_exposure", "sum"),
        mean_intensity=("intensity", "mean"),
    ).reset_index()
    by_type["exposure_ratio"] = (by_type["high_exposure"] / by_type["count"]).round(3)
    by_type.to_csv(DATA_DIR / "vulnerable_exposure_summary.csv",
                   index=False, encoding="utf-8-sig")

    # 前端友好 JSON
    exposure_json = {
        "meta": {
            "module": "step22_vulnerable_facilities",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "magnitude": mag,
            "note": "暴露度 = 位于烈度≥VII区（intensity>=7.0）的设施占比",
        },
        "by_type": [
            {
                "type": r["type"],
                "count": int(r["count"]),
                "high_exposure": int(r["high_exposure"]),
                "exposure_ratio": float(r["exposure_ratio"]),
                "mean_intensity": float(r["mean_intensity"]),
            }
            for _, r in by_type.iterrows()
        ],
        "total": int(df.shape[0]),
    }
    with open(DATA_DIR / "vulnerable_exposure.json", "w", encoding="utf-8") as f:
        json.dump(exposure_json, f, ensure_ascii=False, indent=2)

    # GeoJSON 输出
    gdf = gpd.GeoDataFrame(df, geometry=[Point(x, y) for x, y in zip(df["lon"], df["lat"])],
                           crs="EPSG:4326")
    gdf.to_file(DATA_DIR / "vulnerable_facilities.geojson", driver="GeoJSON")
    return by_type


def main():
    print("=" * 60)
    print("脆弱群体设施采集（学校/养老院/福利院）")
    print("=" * 60)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    records, quota_failed = collect_all()
    if quota_failed:
        print("\n[WARN] 以下类别采集失败（配额/网络）:")
        for f in quota_failed:
            print(f"  - {f}")
    if not records:
        print("\n[FAIL] 未采集到任何设施——高德配额超限或网络不可达。")
        print("       数据源恢复后（次日配额/更换 key）重跑本脚本即可补全。")
        print("       当前阶段 3 其余交付不受影响。")
        return False

    print(f"\n共采集 {len(records)} 个脆弱设施")
    summary = compute_exposure(records)
    if summary is not None:
        print("\n=== M6.0 暴露度汇总 ===")
        print(summary.to_string(index=False))
    print("\n[OK] 已输出 vulnerable_facilities.geojson + vulnerable_exposure_summary.csv")
    return True


if __name__ == "__main__":
    main()
