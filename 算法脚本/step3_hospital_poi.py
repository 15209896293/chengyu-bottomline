"""
Step 3 (模块0C): 高德API爬取合肥市医院POI数据
输出: 数据文件/hefei_hospital.csv
"""
import os
import time
import requests
import pandas as pd
from pathlib import Path

# ── 配置 ────────────────────────────────────────────────
# ⚠️ 高德Key必须是"Web服务"类型，不是JS API类型
#    去 https://console.amap.com/dev/key/app 创建Web服务Key
AMAP_KEY = "6b7b1ccf00f53270619fa4f84b8fc0e7"
CITY = "合肥"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "数据文件"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_CSV = OUTPUT_DIR / "hefei_hospital.csv"

POI_TYPES = ["090100", "090200", "090300"]  # 综合医院/专科医院/诊所
TYPE_LABEL = {"090100": "综合医院", "090200": "专科医院", "090300": "诊所"}

# ── 1. 爬取 ─────────────────────────────────────────────
def fetch_poi(keyword: str, poi_type: str, page: int) -> dict:
    """调用高德 /place/text 接口"""
    url = "https://restapi.amap.com/v3/place/text"
    params = {
        "key": AMAP_KEY,
        "keywords": keyword,
        "types": poi_type,
        "city": CITY,
        "offset": 20,
        "page": page,
        "extensions": "all",
    }
    resp = requests.get(url, params=params, timeout=15)
    return resp.json()


all_records = []
for poi_type in POI_TYPES:
    label = TYPE_LABEL[poi_type]
    print(f"\n正在爬取: {label} (type={poi_type})")

    for page in range(1, 101):  # 最多100页
        data = fetch_poi("医院", poi_type, page)
        if data.get("status") != "1":
            print(f"  API错误: {data.get('info')}")
            break

        pois = data.get("pois", [])
        if not pois:
            break

        for p in pois:
            lng_lat = p.get("location", ",")
            lng, lat = (lng_lat.split(",") + ["0", "0"])[:2]
            # tel可能是数组，转成字符串
            tel_raw = p.get("tel", "")
            if isinstance(tel_raw, list):
                tel_raw = "; ".join(tel_raw)
            all_records.append({
                "name": p.get("name", ""),
                "lng": float(lng),
                "lat": float(lat),
                "address": p.get("address", ""),
                "tel": tel_raw,
                "type": label,
            })

        print(f"  page {page}: {len(pois)} 条, 累计 {len(all_records)}")
        time.sleep(0.2)

        if len(pois) < 20:
            break  # 最后一页

print(f"\n总爬取: {len(all_records)} 条")

# ── 2. 检查API是否正常 ─────────────────────────────────
if len(all_records) == 0:
    print("\n" + "=" * 50)
    print("API 未返回数据！请检查：")
    print("1. 高德Key是否为\"Web服务\"类型？（当前key可能是JS API类型）")
    print("2. 去 https://console.amap.com/dev/key/app 创建新的Web服务Key")
    print("3. 将新Key填入本脚本顶部的 AMAP_KEY 变量")
    print("=" * 50)
    print("\n脚本退出（不生成CSV）。换Key后再运行。")
    exit(1)

# ── 3. 去重 ─────────────────────────────────────────────
# 强制所有字段转为字符串，避免list/unhashable导致drop_duplicates崩溃
for r in all_records:
    for k in r:
        if isinstance(r[k], list):
            r[k] = "; ".join(str(x) for x in r[k])
        elif not isinstance(r[k], str):
            r[k] = str(r[k])

df = pd.DataFrame(all_records)
before = len(df)
# 用 name + address前10字 做去重key（高德地址格式不统一）
df["_key"] = df["name"] + df["address"].str[:10]
df = df.drop_duplicates(subset=["_key"])
df = df.drop(columns=["_key"])
print(f"去重: {before} -> {len(df)} (移除 {before - len(df)} 条)")

# ── 3. 保存 ─────────────────────────────────────────────
df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
print(f"已保存 -> {OUTPUT_CSV}")


# ── 4. 自检验收 ─────────────────────────────────────────
def self_test():
    df = pd.read_csv(OUTPUT_CSV)
    print(f"\n=== 自检验收 ===")
    print(f"医院总数: {len(df)}")
    print(f"类型分布:\n{df['type'].value_counts().to_string()}")
    print(f"\n前5条:\n{df.head().to_string()}")
    assert df['lng'].dtype == 'float64', "lng不是浮点数"
    assert df['lat'].dtype == 'float64', "lat不是浮点数"
    assert len(df) > 50, f"合肥医院应该至少50+，实际只有{len(df)}，可能漏爬了"
    print("\n模块0C验收通过")


self_test()
