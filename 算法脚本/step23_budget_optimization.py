"""
step23_budget_optimization.py — 预算约束下的韧性投资优化（金融语言：资本配置）

把"加固策略"建模为可量化的投资组合：
  - 干预项：加固关键路段（每条成本 c_road，提升医疗/救援功能率）
            增设临时医疗点（每个成本 c_med，提升医疗功能率）
  - 给定预算 B，选择 (路段数 r, 医疗点数 m) 组合使韧性收益最大化
  - 收益度量：医疗功能率提升（主导城市崩溃的变量）+ 城市崩溃状态翻转

输出：数据文件/budget_optimization.json
  - 预算梯度（0~10 亿，0.5 步长）→ 最优组合 + 收益曲线
  - 边际收益（每亿元提升）——"预算边际价值递减"叙事
  - 与现有策略 A/B/C 的对照

参数基准来自 prevention_strategy.csv（step14 实际推演结果）：
  - 策略 A（加固 10 路段）：medical 0.2676→0.4401，rescue 0.4156→0.5584，城市崩溃翻转
  - 策略 B（增设 3 医疗点）：medical 0.2676→0.2727
线性假设：单位干预收益 = 策略总收益 / 干预数量（一阶近似，答辩需说明）。
"""
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "数据文件"

# 单位干预成本（亿元，领域知识假设，可配置）
COST_ROAD_YI = 0.20    # 加固一条关键路段
COST_MED_YI = 0.50     # 增设一个临时医疗点

# 策略基线（prevention_strategy.csv）
BASE_MEDICAL = 0.2676
BASE_RESCUE = 0.4156

# 策略 A 的单位收益（10 路段）
MEDICAL_PER_ROAD = (0.4401 - BASE_MEDICAL) / 10
RESCUE_PER_ROAD = (0.5584 - BASE_RESCUE) / 10
# 策略 B 的单位收益（3 医疗点）
MEDICAL_PER_MED = (0.2727 - BASE_MEDICAL) / 3

MAX_ROADS = 10   # 与策略 A 一致的上限
MAX_MEDS = 6


def evaluate(budget_yi):
    """给定预算，枚举 (roads, meds) 组合求最优。"""
    best = None
    for r in range(0, MAX_ROADS + 1):
        for m in range(0, MAX_MEDS + 1):
            cost = r * COST_ROAD_YI + m * COST_MED_YI
            if cost > budget_yi + 1e-9:
                continue
            medical = min(BASE_MEDICAL + MEDICAL_PER_ROAD * r + MEDICAL_PER_MED * m, 1.0)
            rescue = min(BASE_RESCUE + RESCUE_PER_ROAD * r, 1.0)
            city_saved = medical >= 0.30 and rescue >= 0.40  # 阈值翻转
            if best is None or medical > best["medical_after"]:
                best = {
                    "budget_yi": round(budget_yi, 1),
                    "roads_repaired": r,
                    "med_points": m,
                    "cost_yi": round(cost, 2),
                    "medical_after": round(medical, 4),
                    "rescue_after": round(rescue, 4),
                    "city_saved": bool(city_saved),
                    "medical_gain": round(medical - BASE_MEDICAL, 4),
                }
    return best


def main():
    print("=" * 60)
    print("预算约束韧性投资优化")
    print("=" * 60)
    print(f"单位成本：加固路段 {COST_ROAD_YI} 亿/条 | 医疗点 {COST_MED_YI} 亿/个")

    budgets = [round(b, 1) for b in [x / 2 for x in range(0, 21)]]  # 0~10亿
    results = [evaluate(b) for b in budgets]

    print(f"\n{'预算(亿)':>8} {'路段':>4} {'医疗点':>4} {'成本':>6} {'医疗率':>8} {'城市翻转':>8}")
    prev_med = None
    marginal = []
    for r in results:
        mark = "★" if r["city_saved"] else ""
        print(f"{r['budget_yi']:>8.1f} {r['roads_repaired']:>4} {r['med_points']:>4} "
              f"{r['cost_yi']:>6.2f} {r['medical_after']:>8.4f} {mark:>6}")
        if prev_med is not None and r["budget_yi"] > 0:
            gain = r["medical_gain"] - prev_med
            if r["budget_yi"] <= 3.0:  # 只统计前 3 亿的边际（预算段）
                marginal.append({
                    "budget_yi": r["budget_yi"],
                    "marginal_gain": round(gain, 4),
                })
        prev_med = r["medical_gain"]

    # 关键节点：城市崩溃翻转的最小预算
    first_saved = next((r for r in results if r["city_saved"]), None)
    no_intervention = results[0]

    report = {
        "meta": {
            "module": "step23_budget_optimization",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "model": "线性单位干预 + 预算枚举",
            "cost_assumptions": {"road_yi": COST_ROAD_YI, "med_point_yi": COST_MED_YI},
            "basis": "prevention_strategy.csv（step14 实际推演）",
            "note": "单位收益为策略总收益的线性均摊（一阶近似）；"
                    "收益度量=医疗功能率提升，城市翻转=医疗≥0.30且救援≥0.40",
        },
        "budget_curve": results,
        "highlights": {
            "min_budget_for_city_saved_yi": (
                first_saved["budget_yi"] if first_saved else None),
            "min_budget_combination": (
                {"roads": first_saved["roads_repaired"],
                 "med_points": first_saved["med_points"]} if first_saved else None),
            "no_intervention_medical": no_intervention["medical_after"],
            "full_intervention_medical": results[-1]["medical_after"],
            "marginal_gains": marginal,
        },
        "interpretation": (
            f"在 {first_saved['budget_yi'] if first_saved else '—'} 亿元预算下，"
            f"优先加固 {first_saved['roads_repaired'] if first_saved else 0} 条关键路段"
            f"即可使医疗功能率跨过 30% 崩溃线、城市从'崩溃'翻转为'可维持'。"
            "加固路段的收益远高于增设医疗点（单位收益 ~10:1），"
            "预算应优先投向路网韧性——这是与直觉相反的发现："
            "医疗崩溃的根源在交通，不在医院本身。"
        ),
    }

    out_path = DATA_DIR / "budget_optimization.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n已保存: {out_path}")

    ok = verify(report)
    print("\n[OK] 自检通过" if ok else "\n[FAIL] 自检失败")
    return ok


def verify(report):
    """自检。"""
    reasons = []
    h = report["highlights"]
    curve = report["budget_curve"]
    # 收益单调不减
    meds = [c["medical_after"] for c in curve]
    if meds != sorted(meds):
        reasons.append("医疗功能率不随预算单调")
    # 城市翻转阈值一致性
    if h["min_budget_for_city_saved_yi"] is not None:
        saved = [c for c in curve if c["city_saved"]]
        if saved and saved[0]["budget_yi"] != h["min_budget_for_city_saved_yi"]:
            reasons.append("城市翻转最小预算不一致")
    # 成本不超预算
    for c in curve:
        if c["cost_yi"] > c["budget_yi"] + 1e-9:
            reasons.append(f"预算 {c['budget_yi']} 组合成本超支")
    for r in reasons:
        print(f"  [FAIL] {r}")
    return len(reasons) == 0


if __name__ == "__main__":
    main()
