"""
crawl_real_facilities.py — 用高德 API 爬取合肥真实设施 POI
替换原模拟数据：消防站/化工厂/加油站 → facilities_hazards/rescue
公园/体育场 → facilities_shelters

输出：
  - 数据文件/facilities_hazards_real.geojson   (真实危险源)
  - 数据文件/facilities_rescue_real.geojson    (真实救援力量)
  - 数据文件/facilities_shelters_real.geojson   (真实避难场所)
  - 数据文件/facilities_summary.csv            (汇总)

用法：python src/crawl_real_facilities.py
注意：不影响现有 _real 后缀文件以外的任何项目文件
"""
import os, sys, time, json
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


def fetch_poi(keyword, poi_type, page=1, city="合肥", retries=3):
    """调用高德 /place/text 接口（含重试）"""
    url = "https://restapi.amap.com/v3/place/text"
    params = {
        "key": AMAP_KEY,
        "keywords": keyword,
        "types": poi_type,
        "city": city,
        "offset": 20,
        "page": page,
        "extensions": "all",
    }
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()
            if data.get("status") != "1":
                return [], 0
            pois = data.get("pois", [])
            total = int(data.get("count", 0))
            return pois, total
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(1.5)
            else:
                print(f"    Retry failed: {e}")
                return [], 0
    return [], 0


def crawl_category(keyword, poi_type, category_name, max_pages=10):
    """爬取一个类别的所有 POI，返回列表"""
    all_pois = []
    for page in range(1, max_pages + 1):
        pois, total = fetch_poi(keyword, poi_type, page)
        if not pois:
            break
        all_pois.extend(pois)
        print(f"  {category_name} page {page}: {len(pois)} results (total: {total})")
        if page * 20 >= total:
            break
        time.sleep(0.3)  # 避免触发限流
    return all_pois


def main():
    print("=" * 60)
    print("合肥真实设施 POI 爬取")
    print("=" * 60)

    # ═══════════════════════════════════════
    # 1. 危险源：化工厂 + 加油站
    # ═══════════════════════════════════════
    print("\n[1/5] 爬取化工厂/化工企业...")
    chem_pois = crawl_category("化工厂", "", "化工厂")  # 不限类型
    chem_pois += crawl_category("化工有限公司", "", "化工企业")
    chem_pois += crawl_category("危险化学品", "", "危化品")
    # 去重
    seen = set(); unique = []
    for p in chem_pois:
        addr = p.get("address","")
        if isinstance(addr, list): addr = addr[0] if addr else ""
        key = str(p.get("name","")) + str(addr)[:6]
        if key not in seen: seen.add(key); unique.append(p)
    chem_pois = unique
    print(f"  共获取 {len(chem_pois)} 条化工厂")

    print("\n[2/5] 爬取加油站...")
    gas_pois = crawl_category("加油站", "010100|050300", "加油站")
    print(f"  共获取 {len(gas_pois)} 条加油站")

    # ═══════════════════════════════════════
    # 2. 救援力量：消防站 + 医院（作为急救力量）
    # ═══════════════════════════════════════
    print("\n[3/5] 爬取消防站...")
    fire_pois = crawl_category("消防站", "", "消防站")
    fire_pois += crawl_category("消防救援支队", "", "消防支队")
    fire_pois += crawl_category("消防大队", "", "消防大队")
    fire_pois += crawl_category("消防中队", "", "消防中队")
    seen = set(); unique = []
    for p in fire_pois:
        addr = p.get("address","")
        if isinstance(addr, list): addr = addr[0] if addr else ""
        key = str(p.get("name","")) + str(addr)[:6]
        if key not in seen: seen.add(key); unique.append(p)
    fire_pois = unique
    print(f"  共获取 {len(fire_pois)} 条消防站")

    # ═══════════════════════════════════════
    # 3. 避难场所：公园 + 体育场 + 学校操场
    # ═══════════════════════════════════════
    print("\n[4/5] 爬取公园...")
    park_pois = crawl_category("公园", "110100", "公园")  # 风景名胜→公园
    park_pois += crawl_category("城市广场", "110100", "广场")
    print(f"  共获取 {len(park_pois)} 条公园/广场")

    print("\n[5/5] 爬取体育场...")
    stadium_pois = crawl_category("体育场", "080200", "体育场")  # 体育休闲→体育场馆
    stadium_pois += crawl_category("体育馆", "080200", "体育馆")
    stadium_pois += crawl_category("会展中心", "080200", "会展中心")
    print(f"  共获取 {len(stadium_pois)} 条体育场馆")

    # ═══════════════════════════════════════
    # 数据清洗与输出
    # ═══════════════════════════════════════
    print("\n" + "=" * 60)
    print("数据清洗与输出")
    print("=" * 60)

    def pois_to_gdf(pois, category, subtype_label):
        """POI 列表 → GeoDataFrame"""
        if not pois:
            return gpd.GeoDataFrame({
                "name": [], "lng": [], "lat": [], "type": [], "subtype": [], "address": [],
                "geometry": []
            }, crs="EPSG:4326")
        records = []
        for p in pois:
            loc = p.get("location", "0,0")
            try:
                lng, lat = loc.split(",")
            except:
                continue
            addr = p.get("address", "")
            if isinstance(addr, list): addr = addr[0] if addr else ""
            tel = p.get("tel", "")
            if isinstance(tel, list): tel = tel[0] if tel else ""
            records.append({
                "name": p.get("name", ""),
                "lng": float(lng),
                "lat": float(lat),
                "type": category,
                "subtype": subtype_label,
                "address": str(addr) if addr else "",
                "tel": str(tel) if tel else "",
            })
        gdf = gpd.GeoDataFrame(
            records,
            geometry=gpd.points_from_xy([r["lng"] for r in records], [r["lat"] for r in records]),
            crs="EPSG:4326"
        )
        # 去重：同名+同地址前8字
        gdf["_dup_key"] = gdf["name"] + gdf["address"].str[:8]
        gdf = gdf.drop_duplicates(subset=["_dup_key"])
        gdf = gdf.drop(columns=["_dup_key"])
        return gdf

    # --- 危险源 ---
    haz_chem = pois_to_gdf(chem_pois, "危险源", "化工厂")
    haz_chem["risk_level"] = 3  # 高风险
    haz_chem["hazard_material"] = "危险化学品"
    haz_chem["buffer_radius"] = 800  # 默认影响范围

    haz_gas = pois_to_gdf(gas_pois, "危险源", "加油站")
    haz_gas["risk_level"] = 1  # 中低风险
    haz_gas["hazard_material"] = "汽柴油"
    haz_gas["buffer_radius"] = 300

    hazards_gdf = pd.concat([haz_chem, haz_gas], ignore_index=True)
    for col in ["risk_level","hazard_material","buffer_radius"]:
        if col not in hazards_gdf.columns:
            hazards_gdf[col] = 0
    hazards_gdf["id"] = range(len(hazards_gdf))
    print(f"\n危险源: {len(hazards_gdf)} 个 (化工厂 {len(haz_chem)} + 加油站 {len(haz_gas)})")

    # --- 救援力量 ---
    fire_gdf = pois_to_gdf(fire_pois, "救援力量", "消防站")
    fire_gdf["capacity"] = 5   # 消防车数量估算
    fire_gdf["capacity_unit"] = "辆"
    fire_gdf["coverage_radius"] = 3000  # 消防站标准覆盖半径

    rescue_gdf = fire_gdf.copy()
    rescue_gdf["id"] = range(len(rescue_gdf))
    print(f"救援力量: {len(rescue_gdf)} 个消防站")

    # --- 避难场所 ---
    park_gdf = pois_to_gdf(park_pois, "避难所", "公园/广场")
    park_gdf["capacity"] = 5000  # 估算容纳人数

    stadium_gdf = pois_to_gdf(stadium_pois, "避难所", "体育/会展")
    stadium_gdf["capacity"] = 10000

    shelters_gdf = pd.concat([park_gdf, stadium_gdf], ignore_index=True)
    shelters_gdf["id"] = range(len(shelters_gdf))
    print(f"避难场所: {len(shelters_gdf)} 个 (公园 {len(park_gdf)} + 体育 {len(stadium_gdf)})")

    # 存 GeoJSON (EPSG:4490, 与现有数据格式一致)
    for gdf, fname in [
        (hazards_gdf, "facilities_hazards_real.geojson"),
        (rescue_gdf, "facilities_rescue_real.geojson"),
        (shelters_gdf, "facilities_shelters_real.geojson"),
    ]:
        gdf_4490 = gdf.to_crs("EPSG:4490")
        gdf_4490.to_file(DATA_DIR / fname, driver="GeoJSON")
        print(f"  Saved: {fname} ({len(gdf)} features)")

    # 汇总 CSV
    summary = pd.DataFrame({
        "类别": ["危险源-化工厂","危险源-加油站","救援-消防站","避难-公园/广场","避难-体育场馆"],
        "数量": [len(haz_chem), len(haz_gas), len(fire_gdf), len(park_gdf), len(stadium_gdf)],
        "数据来源": ["高德API"] * 5,
        "旧(模拟)": [7, 6, 11, 6, 4],
        "旧状态": ["❌模拟","❌模拟","❌模拟","❌模拟","❌模拟"],
        "新状态": ["✅真实","✅真实","✅真实","✅真实","✅真实"],
    })
    summary_path = DATA_DIR / "facilities_summary.csv"
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    print(f"\n  Summary: {summary_path}")
    print(summary.to_string(index=False))

    print("\n" + "=" * 60)
    print("完成。真实设施 POI 已保存为 *_real.geojson")
    print("如需替换现有模拟数据，执行：")
    print("  cp 数据文件/facilities_hazards_real.geojson 数据文件/facilities_hazards.geojson")
    print("  cp 数据文件/facilities_rescue_real.geojson 数据文件/facilities_rescue.geojson")
    print("  cp 数据文件/facilities_shelters_real.geojson 数据文件/facilities_shelters.geojson")
    print("=" * 60)


if __name__ == "__main__":
    main()
