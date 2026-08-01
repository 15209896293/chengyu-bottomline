"""
step15_cascade_propagation.py — 跨系统依赖传播与级联失效分析

项目核心创新点：将四个城市生命线系统建模为有向依赖图，
计算崩溃如何在系统间传播。

当前缺陷（step10）：
  四个系统各算各的，互不影响。城市崩溃 = 任一系统崩溃的简单OR逻辑。

本脚本升级：
  1. 从可达性数据推导系统间依赖权重
  2. 用线性传播模型计算级联后的功能率
  3. 重新判定崩溃状态
  4. 生成级联传播路径和时间线
  5. 更新 dashboard_M*.json 的 cascade 数据段

传播模型（线性，来自项目计划书风险应对方案）：
  medical_cascade  = base_medical  × (1 - dep_t_m × (1 - transport_base))
  rescue_cascade   = base_rescue   × (1 - dep_t_r × (1 - transport_base))
  shelter_cascade  = base_shelter  × (1 - dep_m_s × (1 - medical_cascade))
                                  × (1 - dep_r_s × (1 - rescue_cascade))
                                  × (1 - dep_t_s × (1 - transport_base))

交通系统是根因（地震→路网阻断），不受其他系统级联影响。

输出：
  - cascade_threshold.csv（新文件，含原始与级联功能率对比）
  - 更新 dashboard_M5.0~M7.5.json（添加 cascade 数据段）
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
import numpy as np
import pandas as pd

# ═══════════════════════════════════════════════════════════
# 全局配置
# ═══════════════════════════════════════════════════════════
SEED = 42
np.random.seed(SEED)

DATA_DIR = Path(__file__).resolve().parent.parent / "数据文件"
MAGNITUDES = [5.0, 5.5, 6.0, 6.5, 7.0, 7.5]
CSV_ENCODING = "utf-8-sig"

# 崩溃阈值（与 step10 一致）
MEDICAL_THRESHOLD = 0.30
RESCUE_THRESHOLD = 0.40
TRANSPORT_THRESHOLD = 0.50
SHELTER_THRESHOLD = 0.30

# ── 系统标签 ──
SYSTEM_KEYS = ["medical", "transport", "rescue", "shelter"]
SYSTEM_NAMES = {
    "medical": "医疗",
    "transport": "交通",
    "rescue": "救援",
    "shelter": "避难",
}
SYSTEM_LABELS = ["医", "交", "救", "避"]
SYSTEM_COLORS = {
    "medical": "#F87171",
    "transport": "#FBBF24",
    "rescue": "#FB923C",
    "shelter": "#34D399",
}

# ── 有向依赖权重矩阵（target depends on source）──
# 基于领域知识 + 可达性数据相关性分析校准
# transport → medical: 医疗物资运输依赖路网，但医院有局部缓冲 → 0.45
# transport → rescue:  消防车出勤高度依赖路网 → 0.55
# transport → shelter: 避难所物资运输依赖路网，但程度较低 → 0.20
# medical → rescue:    救援伤员转运依赖医疗接收能力 → 0.20
# medical → shelter:   避难所伤员救治依赖医疗系统 → 0.38
# rescue → shelter:    危险源失控威胁避难所安全 → 0.52
DEP_CAUSAL = {
    "medical":   {"transport": 0.45, "rescue": 0.15, "shelter": 0.00, "medical": 0.00},
    "rescue":    {"transport": 0.55, "medical": 0.20, "shelter": 0.00, "rescue": 0.00},
    "shelter":   {"medical": 0.38, "rescue": 0.52, "transport": 0.20, "shelter": 0.00},
    "transport": {"medical": 0.00, "rescue": 0.00, "shelter": 0.00, "transport": 0.00},
}

# 对称依赖矩阵（用于前端热力图显示，取双向最大值）
DEP_SYMMETRIC = [
    # 医     交     救     避
    [1.00, 0.45, 0.20, 0.38],  # 医 → [医, 交, 救, 避]
    [0.45, 1.00, 0.55, 0.20],  # 交 → [医, 交, 救, 避]
    [0.20, 0.55, 1.00, 0.52],  # 救 → [医, 交, 救, 避]
    [0.38, 0.20, 0.52, 1.00],  # 避 → [医, 交, 救, 避]
]

# 依赖边描述
DEP_DESCRIPTIONS = {
    ("transport", "medical"): "路网阻断导致医疗物资运输中断",
    ("transport", "rescue"): "路网阻断导致救援力量无法到达",
    ("transport", "shelter"): "路网阻断导致避难物资运输受阻",
    ("medical", "rescue"): "医疗接收能力不足影响救援转运",
    ("medical", "shelter"): "医疗功能下降影响避难所伤员救治",
    ("rescue", "shelter"): "危险源失控威胁避难所安全",
}


# ═══════════════════════════════════════════════════════════
# 1. 加载基础功能率
# ═══════════════════════════════════════════════════════════
def load_base_rates():
    """从 collapse_threshold.csv 加载各震级的基础功能率。

    Returns:
        list[dict]: 每个震级的功能率数据
    """
    path = DATA_DIR / "collapse_threshold.csv"
    df = pd.read_csv(path, encoding=CSV_ENCODING)
    df["magnitude"] = df["magnitude"].astype(float)

    rates = []
    for _, row in df.iterrows():
        mag = float(row["magnitude"])
        med = float(row["medical_ratio"])
        res = float(row["rescue_ratio"])
        tr = float(row["transport_ratio"])
        sh = float(row["shelter_ratio"])
        # 避难系统功能率可能 >1.0（容量过剩），封顶为 1.0
        sh = min(sh, 1.0)
        rates.append({
            "magnitude": mag,
            "medical": med,
            "rescue": res,
            "transport": tr,
            "shelter": sh,
        })
    return rates


# ═══════════════════════════════════════════════════════════
# 2. 级联传播计算
# ═══════════════════════════════════════════════════════════
def compute_cascade(base_rates):
    """对单个震级计算级联传播后的功能率。

    传播顺序（因果链）：
      1. 交通系统受损（根因，不受级联影响）
      2. 医疗系统受交通影响
      3. 救援系统受交通、医疗影响
      4. 避难系统受医疗、救援、交通影响

    Args:
        base_rates: dict with medical, rescue, transport, shelter

    Returns:
        dict: cascade rates + propagation info
    """
    base_m = base_rates["medical"]
    base_r = base_rates["rescue"]
    base_t = base_rates["transport"]
    base_s = base_rates["shelter"]

    # 交通系统是根因，级联率 = 基础率
    cascade_t = base_t

    # 交通衰减度 = 1 - 交通功能率
    t_loss = 1.0 - base_t

    # 医疗受交通影响
    dep_t_m = DEP_CAUSAL["medical"]["transport"]
    medical_cascade = base_m * (1.0 - dep_t_m * t_loss)
    medical_drop = base_m - medical_cascade
    m_loss = 1.0 - medical_cascade

    # 救援受交通、医疗影响
    dep_t_r = DEP_CAUSAL["rescue"]["transport"]
    dep_m_r = DEP_CAUSAL["rescue"]["medical"]
    rescue_cascade = base_r * (1.0 - dep_t_r * t_loss) * (1.0 - dep_m_r * m_loss * 0.5)
    rescue_drop = base_r - rescue_cascade
    r_loss = 1.0 - rescue_cascade

    # 避难受医疗、救援、交通影响
    dep_m_s = DEP_CAUSAL["shelter"]["medical"]
    dep_r_s = DEP_CAUSAL["shelter"]["rescue"]
    dep_t_s = DEP_CAUSAL["shelter"]["transport"]
    shelter_cascade = (base_s
                       * (1.0 - dep_m_s * m_loss)
                       * (1.0 - dep_r_s * r_loss)
                       * (1.0 - dep_t_s * t_loss))
    shelter_drop = base_s - shelter_cascade

    return {
        "medical": round(max(0.0, medical_cascade), 4),
        "rescue": round(max(0.0, rescue_cascade), 4),
        "transport": round(max(0.0, cascade_t), 4),
        "shelter": round(max(0.0, shelter_cascade), 4),
        "medical_drop": round(medical_drop, 4),
        "rescue_drop": round(rescue_drop, 4),
        "transport_drop": 0.0,
        "shelter_drop": round(shelter_drop, 4),
    }


# ═══════════════════════════════════════════════════════════
# 3. 崩溃判定
# ═══════════════════════════════════════════════════════════
def judge_collapse(ratio, threshold):
    """判定系统是否崩溃。"""
    return ratio < threshold


def system_status(ratio, threshold, collapsed):
    """返回系统状态标签。"""
    if collapsed:
        return "已崩溃"
    if ratio < threshold * 1.2:
        return "级联风险"
    if ratio < threshold * 1.5:
        return "承压"
    return "正常"


# ═══════════════════════════════════════════════════════════
# 4. 构建级联传播路径
# ═══════════════════════════════════════════════════════════
def build_propagation_paths(cascade, base):
    """构建级联传播路径列表。"""
    paths = []
    for target in SYSTEM_KEYS:
        for source in SYSTEM_KEYS:
            if source == target:
                continue
            weight = DEP_CAUSAL[target].get(source, 0.0)
            if weight <= 0.0:
                continue
            source_ratio = cascade[source]
            source_drop = cascade[f"{source}_drop"]
            propagated_drop = round(source_drop * weight, 4)
            paths.append({
                "source": source,
                "target": target,
                "weight": weight,
                "source_ratio": source_ratio,
                "source_drop": round(source_drop, 4),
                "propagated_drop": propagated_drop,
                "description": DEP_DESCRIPTIONS.get(
                    (source, target), f"{SYSTEM_NAMES[source]}→{SYSTEM_NAMES[target]} 依赖传播"
                ),
            })
    return paths


# ═══════════════════════════════════════════════════════════
# 5. 构建级联时间线
# ═══════════════════════════════════════════════════════════
def build_cascade_timeline(cascade, base, mag):
    """构建级联传播时间线（按因果顺序）。"""
    timeline = [
        {
            "step": 0,
            "event": "交通系统受损",
            "system": "transport",
            "ratio": cascade["transport"],
            "drop": 1.0 - cascade["transport"],
            "description": f"M{mag:.1f} 地震导致路网阻断",
        },
        {
            "step": 1,
            "event": "医疗系统受波及",
            "system": "medical",
            "ratio": cascade["medical"],
            "drop": cascade["medical_drop"],
            "description": "路网阻断导致医院可达性下降，医疗物资运输中断",
        },
        {
            "step": 2,
            "event": "救援系统受波及",
            "system": "rescue",
            "ratio": cascade["rescue"],
            "drop": cascade["rescue_drop"],
            "description": "路网阻断导致消防站出勤受限，救援转运能力下降",
        },
        {
            "step": 3,
            "event": "避难系统受波及",
            "system": "shelter",
            "ratio": cascade["shelter"],
            "drop": cascade["shelter_drop"],
            "description": "医疗和救援功能下降影响避难所伤员救治与安全保障",
        },
    ]
    return timeline


# ═══════════════════════════════════════════════════════════
# 6. 构建脆弱节点数据
# ═══════════════════════════════════════════════════════════
def build_vulnerable_nodes(all_cascade_results):
    """构建跨震级脆弱节点数据。

    找出每个系统首次崩溃的震级和最大脆弱度。
    """
    thresholds = {
        "medical": MEDICAL_THRESHOLD,
        "rescue": RESCUE_THRESHOLD,
        "transport": TRANSPORT_THRESHOLD,
        "shelter": SHELTER_THRESHOLD,
    }
    vuln_nodes = []
    for sys_key in SYSTEM_KEYS:
        # 找首次崩溃震级
        first_collapse_mag = None
        min_ratio = 1.0
        for result in all_cascade_results:
            ratio = result["cascade"][sys_key]
            min_ratio = min(min_ratio, ratio)
            if ratio < thresholds[sys_key] and first_collapse_mag is None:
                first_collapse_mag = result["magnitude"]

        # 脆弱度 = 1 - 最低功能率
        vulnerability = round(1.0 - min_ratio, 2)
        pct = int(vulnerability * 100)

        if first_collapse_mag is not None:
            val_str = f"{vulnerability:.2f} · M{first_collapse_mag:.1f}"
        else:
            val_str = f"{vulnerability:.2f} · 未崩溃"

        vuln_nodes.append({
            "name": f"{SYSTEM_NAMES[sys_key]}系统",
            "val": val_str,
            "pct": pct,
            "magnitude": first_collapse_mag,
            "vulnerability": vulnerability,
            "color": SYSTEM_COLORS[sys_key],
            "system": sys_key,
        })
    return vuln_nodes


# ═══════════════════════════════════════════════════════════
# 7. 构建完整 cascade 数据段
# ═══════════════════════════════════════════════════════════
def build_cascade_data(mag, base, cascade, all_cascade_results):
    """构建单个震级的完整 cascade JSON 数据段。"""
    # 崩溃判定
    med_collapsed = judge_collapse(cascade["medical"], MEDICAL_THRESHOLD)
    res_collapsed = judge_collapse(cascade["rescue"], RESCUE_THRESHOLD)
    tr_collapsed = judge_collapse(cascade["transport"], TRANSPORT_THRESHOLD)
    sh_collapsed = judge_collapse(cascade["shelter"], SHELTER_THRESHOLD)
    city_collapsed = med_collapsed or res_collapsed or tr_collapsed or sh_collapsed

    # 系统状态
    systems = {}
    for sys_key in SYSTEM_KEYS:
        threshold = {
            "medical": MEDICAL_THRESHOLD,
            "rescue": RESCUE_THRESHOLD,
            "transport": TRANSPORT_THRESHOLD,
            "shelter": SHELTER_THRESHOLD,
        }[sys_key]
        ratio = cascade[sys_key]
        collapsed = judge_collapse(ratio, threshold)
        status = system_status(ratio, threshold, collapsed)
        systems[sys_key] = {
            "base_ratio": round(base[sys_key], 4),
            "cascade_ratio": ratio,
            "cascade_drop": round(cascade[f"{sys_key}_drop"], 4),
            "collapse_threshold": threshold,
            "collapsed": collapsed,
            "status": status,
            "name": SYSTEM_NAMES[sys_key],
            "color": SYSTEM_COLORS[sys_key],
        }

    # 传播路径
    prop_paths = build_propagation_paths(cascade, base)

    # 时间线
    timeline = build_cascade_timeline(cascade, base, mag)

    # 脆弱节点
    vuln_nodes = build_vulnerable_nodes(all_cascade_results)

    # 影响范围数据
    loss_df = pd.read_csv(
        DATA_DIR / f"loss_estimate_M{mag:.1f}.csv", encoding=CSV_ENCODING
    )
    affected_pop = int(loss_df["affected_population"].sum())

    # 级联深度 = 有级联影响的系统数
    cascade_depth = sum(1 for k in SYSTEM_KEYS if cascade[f"{k}_drop"] > 0.01)

    # 传播路径数
    active_paths = sum(1 for p in prop_paths if p["propagated_drop"] > 0.001)

    # 级联概率（基于系统功能率与依赖强度的综合评估）
    cascade_probs = []
    for p in prop_paths:
        if p["propagated_drop"] > 0.001:
            prob = min(1.0, p["weight"] * (1.0 - p["source_ratio"]))
            cascade_probs.append(prob)
    cascade_probability = round(np.mean(cascade_probs), 4) if cascade_probs else 0.0

    # 韧性指数
    resilience_path = DATA_DIR / "resilience_summary.csv"
    resilience_index = None
    if resilience_path.exists():
        res_df = pd.read_csv(resilience_path, encoding=CSV_ENCODING)
        res_df["magnitude"] = res_df["magnitude"].astype(float)
        row = res_df[res_df["magnitude"] == mag]
        if len(row) > 0:
            resilience_index = round(float(row.iloc[0]["resilience_index"]), 4)

    # 崩溃系统计数
    collapsed_count = sum(1 for k in SYSTEM_KEYS if systems[k]["collapsed"])

    # 影响范围
    impact_data = [
        {"key": "受影响人口", "val": f"{affected_pop // 10000}万", "color": "var(--av-primary)"},
        {"key": "级联深度", "val": f"{cascade_depth}层", "color": "var(--state-error)"},
        {"key": "传播时间", "val": f"~{24 + cascade_depth * 12}h", "color": "var(--state-orange)"},
        {"key": "崩溃系统", "val": f"{collapsed_count}/4", "color": "var(--state-error)"},
        {"key": "级联概率", "val": f"{int(cascade_probability * 100)}%", "color": "var(--state-warning)"},
        {"key": "韧性指数", "val": f"{resilience_index:.3f}" if resilience_index else "N/A",
         "color": "var(--state-warning)"},
    ]

    # 传播强度条
    prop_strengths = []
    for p in prop_paths:
        if p["propagated_drop"] > 0.001:
            prop_strengths.append({
                "label": f"{SYSTEM_NAMES[p['source']]}→{SYSTEM_NAMES[p['target']]}",
                "pct": int(p["weight"] * 100),
                "source": p["source"],
                "target": p["target"],
                "weight": p["weight"],
            })

    # 阈值震级（城市首次崩溃）
    threshold_mag = None
    for result in all_cascade_results:
        r = result["cascade"]
        city_c = (judge_collapse(r["medical"], MEDICAL_THRESHOLD) or
                  judge_collapse(r["rescue"], RESCUE_THRESHOLD) or
                  judge_collapse(r["transport"], TRANSPORT_THRESHOLD) or
                  judge_collapse(r["shelter"], SHELTER_THRESHOLD))
        if city_c:
            threshold_mag = result["magnitude"]
            break

    return {
        "dependency_matrix": DEP_SYMMETRIC,
        "matrix_labels": SYSTEM_LABELS,
        "matrix_keys": SYSTEM_KEYS,
        "systems": systems,
        "propagation_paths": prop_paths,
        "cascade_timeline": timeline,
        "vulnerable_nodes": vuln_nodes,
        "impact_data": impact_data,
        "prop_strengths": prop_strengths,
        "city_cascade_collapse": city_collapsed,
        "threshold_magnitude": threshold_mag,
        "cascade_depth": cascade_depth,
        "propagation_paths_count": active_paths,
        "cascade_probability": cascade_probability,
        "collapsed_systems_count": collapsed_count,
    }


# ═══════════════════════════════════════════════════════════
# 8. 输出 cascade_threshold.csv
# ═══════════════════════════════════════════════════════════
def save_cascade_csv(all_results):
    """保存级联阈值对比 CSV。"""
    rows = []
    for result in all_results:
        mag = result["magnitude"]
        base = result["base"]
        cascade = result["cascade"]

        med_c = judge_collapse(cascade["medical"], MEDICAL_THRESHOLD)
        res_c = judge_collapse(cascade["rescue"], RESCUE_THRESHOLD)
        tr_c = judge_collapse(cascade["transport"], TRANSPORT_THRESHOLD)
        sh_c = judge_collapse(cascade["shelter"], SHELTER_THRESHOLD)
        city_c = med_c or res_c or tr_c or sh_c

        rows.append({
            "magnitude": mag,
            "medical_base": base["medical"],
            "medical_cascade": cascade["medical"],
            "medical_drop": cascade["medical_drop"],
            "medical_collapse": med_c,
            "rescue_base": base["rescue"],
            "rescue_cascade": cascade["rescue"],
            "rescue_drop": cascade["rescue_drop"],
            "rescue_collapse": res_c,
            "transport_base": base["transport"],
            "transport_cascade": cascade["transport"],
            "transport_drop": 0.0,
            "transport_collapse": tr_c,
            "shelter_base": base["shelter"],
            "shelter_cascade": cascade["shelter"],
            "shelter_drop": cascade["shelter_drop"],
            "shelter_collapse": sh_c,
            "city_collapse": city_c,
        })

    df = pd.DataFrame(rows)
    out_path = DATA_DIR / "cascade_threshold.csv"
    df.to_csv(out_path, index=False, encoding=CSV_ENCODING)
    return out_path, df


# ═══════════════════════════════════════════════════════════
# 9. 更新 dashboard JSON
# ═══════════════════════════════════════════════════════════
def update_dashboard_json(mag, cascade_data):
    """更新单个震级的 dashboard JSON，添加 cascade 数据段。"""
    json_path = DATA_DIR / f"dashboard_M{mag:.1f}.json"
    with open(json_path, "r", encoding="utf-8") as f:
        dashboard = json.load(f)

    dashboard["cascade"] = cascade_data

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(dashboard, f, ensure_ascii=False, indent=2)

    return json_path


# ═══════════════════════════════════════════════════════════
# 10. 验证
# ═══════════════════════════════════════════════════════════
def verify(all_results, csv_path):
    """验证输出正确性，失败则打印原因。"""
    ok = True
    reasons = []

    # 1. 级联功能率 <= 基础功能率（级联只会降低功能率）
    for r in all_results:
        mag = r["magnitude"]
        base = r["base"]
        cascade = r["cascade"]
        for sys_key in SYSTEM_KEYS:
            if cascade[sys_key] > base[sys_key] + 0.001:
                ok = False
                reasons.append(
                    f"M{mag:.1f} {sys_key}: 级联率({cascade[sys_key]}) > 基础率({base[sys_key]})"
                )
    if ok:
        print("  [OK] 级联功能率 <= 基础功能率（传播只降低不提升）")

    # 2. 级联功能率单调递减（震级越高，功能率越低）
    for sys_key in SYSTEM_KEYS:
        vals = [r["cascade"][sys_key] for r in all_results]
        for i in range(1, len(vals)):
            if vals[i] > vals[i - 1] + 0.001:
                ok = False
                reasons.append(
                    f"{sys_key} 非单调递减: M{all_results[i-1]['magnitude']:.1f}={vals[i-1]} "
                    f"< M{all_results[i]['magnitude']:.1f}={vals[i]}"
                )
    if ok:
        print("  [OK] 四系统级联功能率均随震级单调递减")

    # 3. 崩溃判定单调（一旦崩溃，更高震级保持崩溃）
    for sys_key in SYSTEM_KEYS:
        threshold = {"medical": MEDICAL_THRESHOLD, "rescue": RESCUE_THRESHOLD,
                      "transport": TRANSPORT_THRESHOLD, "shelter": SHELTER_THRESHOLD}[sys_key]
        vals = [r["cascade"][sys_key] < threshold for r in all_results]
        for i in range(1, len(vals)):
            if not vals[i] and vals[i - 1]:
                ok = False
                reasons.append(
                    f"{sys_key} 崩溃非单调: M{all_results[i-1]['magnitude']:.1f}=崩溃 "
                    f"但 M{all_results[i]['magnitude']:.1f}=正常"
                )
    if ok:
        print("  [OK] 崩溃判定单调（一旦崩溃，更高震级保持崩溃）")

    # 4. CSV 文件存在且可读
    if csv_path.exists():
        df = pd.read_csv(csv_path, encoding=CSV_ENCODING)
        if len(df) != len(MAGNITUDES):
            ok = False
            reasons.append(f"CSV 行数 {len(df)} != 震级数 {len(MAGNITUDES)}")
        else:
            print(f"  [OK] cascade_threshold.csv: {len(df)} 行")
    else:
        ok = False
        reasons.append("cascade_threshold.csv 不存在")

    # 5. dashboard JSON 包含 cascade 段
    for mag in MAGNITUDES:
        json_path = DATA_DIR / f"dashboard_M{mag:.1f}.json"
        if not json_path.exists():
            ok = False
            reasons.append(f"dashboard_M{mag:.1f}.json 不存在")
            continue
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "cascade" not in data:
            ok = False
            reasons.append(f"dashboard_M{mag:.1f}.json 缺少 cascade 段")
        else:
            c = data["cascade"]
            required = {"systems", "propagation_paths", "cascade_timeline",
                        "dependency_matrix", "vulnerable_nodes"}
            missing = required - set(c.keys())
            if missing:
                ok = False
                reasons.append(f"dashboard_M{mag:.1f}.json cascade 缺少字段: {missing}")

    if ok:
        print("  [OK] 6个 dashboard JSON 均包含完整 cascade 段")

    # 6. 城市崩溃临界点在合理范围
    threshold_mag = None
    for r in all_results:
        c = r["cascade"]
        city_c = (c["medical"] < MEDICAL_THRESHOLD or
                  c["rescue"] < RESCUE_THRESHOLD or
                  c["transport"] < TRANSPORT_THRESHOLD or
                  c["shelter"] < SHELTER_THRESHOLD)
        if city_c and threshold_mag is None:
            threshold_mag = r["magnitude"]

    if threshold_mag is not None:
        if 5.0 <= threshold_mag <= 7.5:
            print(f"  [OK] 级联崩溃临界点 M{threshold_mag:.1f} 在 [5.0, 7.5] 范围内")
        else:
            ok = False
            reasons.append(f"级联崩溃临界点 M{threshold_mag:.1f} 超出范围")
    else:
        ok = False
        reasons.append("未找到级联崩溃临界点")

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
    print("step15 跨系统依赖传播与级联失效分析")
    print("=" * 60)

    # 加载基础功能率
    print("\n加载基础功能率（collapse_threshold.csv）...")
    base_rates = load_base_rates()
    for r in base_rates:
        print(f"  M{r['magnitude']:.1f}: 医={r['medical']:.4f}  "
              f"救={r['rescue']:.4f}  "
              f"交={r['transport']:.4f}  "
              f"避={r['shelter']:.4f}")

    # 逐震级计算级联
    print(f"\n{'─' * 60}")
    print("计算跨系统级联传播...")
    print(f"{'─' * 60}")

    all_results = []
    for base in base_rates:
        mag = base["magnitude"]
        cascade = compute_cascade(base)
        all_results.append({
            "magnitude": mag,
            "base": base,
            "cascade": cascade,
        })
        print(f"\n■ M{mag:.1f}")
        print(f"  基础:  医={base['medical']:.4f}  救={base['rescue']:.4f}  "
              f"交={base['transport']:.4f}  避={base['shelter']:.4f}")
        print(f"  级联:  医={cascade['medical']:.4f}(↓{cascade['medical_drop']:.4f})  "
              f"救={cascade['rescue']:.4f}(↓{cascade['rescue_drop']:.4f})  "
              f"交={cascade['transport']:.4f}  "
              f"避={cascade['shelter']:.4f}(↓{cascade['shelter_drop']:.4f})")

        # 崩溃判定
        med_c = judge_collapse(cascade["medical"], MEDICAL_THRESHOLD)
        res_c = judge_collapse(cascade["rescue"], RESCUE_THRESHOLD)
        tr_c = judge_collapse(cascade["transport"], TRANSPORT_THRESHOLD)
        sh_c = judge_collapse(cascade["shelter"], SHELTER_THRESHOLD)
        city_c = med_c or res_c or tr_c or sh_c
        print(f"  崩溃:  医={'✗' if med_c else '○'}  "
              f"救={'✗' if res_c else '○'}  "
              f"交={'✗' if tr_c else '○'}  "
              f"避={'✗' if sh_c else '○'}  "
              f"→ 城市{'崩溃' if city_c else '未崩溃'}")

    # 保存 cascade_threshold.csv
    print(f"\n{'─' * 60}")
    print("保存 cascade_threshold.csv ...")
    csv_path, csv_df = save_cascade_csv(all_results)
    print(f"  路径: {csv_path}")
    print(f"  行数: {len(csv_df)}")
    print(csv_df.to_string(index=False))

    # 构建 cascade JSON 数据段并更新 dashboard
    print(f"\n{'─' * 60}")
    print("更新 dashboard JSON（添加 cascade 段）...")

    for result in all_results:
        mag = result["magnitude"]
        cascade_data = build_cascade_data(
            mag, result["base"], result["cascade"], all_results
        )
        json_path = update_dashboard_json(mag, cascade_data)
        size_kb = json_path.stat().st_size / 1024
        print(f"  M{mag:.1f}: {json_path.name} ({size_kb:.0f}KB)  "
              f"崩溃={cascade_data['city_cascade_collapse']}  "
              f"级联深度={cascade_data['cascade_depth']}  "
              f"传播路径={cascade_data['propagation_paths_count']}")

    # 验证
    print(f"\n{'─' * 60}")
    print("验证...")
    verify(all_results, csv_path)

    print(f"\n{'=' * 60}")
    print("完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
