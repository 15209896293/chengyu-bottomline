"""
step26_decision_support.py — 辅助决策：预算 → 城市底线推移决策曲线

把"花多少钱 → 加固什么 → 底线推高多少"建成一条决策曲线，
输出 数据文件/decision_support.json（决策舱前端数据源）。

核心闭环（官方"辅助决策"要求的落地）：
  预算约束 → 最优加固组合（线性分配，同 step23）→ 各系统功能率提升
  → 级联重算 → 城市崩溃临界震级（底线）→ "花 X 亿，底线从 M6.5 推到 M7.0"

干预效果参数来自 prevention_strategy.csv（step14 实际推演）：
  - 策略 A（加固 10 条关键路段，M6.5 场景）：
    medical 0.5681→0.7265 (+0.1584)，rescue 0.381→0.5325 (+0.1515)
  - 策略 B（3 个临时医疗点）：medical +0.003（边际极低）
一阶假设：提升量按加固路段数线性分摊，且与震级无关（保守）。
"""
import json
import math
from datetime import datetime
from pathlib import Path

import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from cascade_model import CascadeModel

DATA_DIR = Path(__file__).resolve().parent.parent / "数据文件"

# 干预单位成本（亿元，与 step23 一致）
COST_ROAD_YI = 0.20
COST_MED_YI = 0.50
MAX_ROADS = 10
MAX_MEDS = 6

# 干预效果（M6.5 场景，来源 prevention_strategy.csv）
MED_GAIN_ROAD_FULL = 0.7265 - 0.5681   # 10 路段全量医疗提升
RES_GAIN_ROAD_FULL = 0.5325 - 0.381    # 10 路段全量救援提升
MED_GAIN_POINT = (0.5711 - 0.5681) / 3  # 每个医疗点


def intervention(budget):
    """预算 → (加固路段数, 医疗点数)。"""
    r = min(MAX_ROADS, int(budget // COST_ROAD_YI))
    rest = budget - r * COST_ROAD_YI
    m = min(MAX_MEDS, int(rest // COST_MED_YI))
    return r, m


def bottom_line_with_gain(gain_m, gain_r):
    """施加功能率提升后，重新计算城市崩溃临界震级（底线）。"""
    model = CascadeModel()
    base_rates = model.load_base_rates()
    for br in base_rates:
        br["medical"] = min(1.0, br["medical"] + gain_m)
        br["rescue"] = min(1.0, br["rescue"] + gain_r)
    # 按震级升序，找第一个城市崩溃
    for br in base_rates:
        cascade = model.compute_cascade(br, propagation_factor=1.0)
        if model.city_collapsed(cascade):
            return float(br["magnitude"])
    return 8.0  # 全震级不崩


def main():
    print("=" * 60)
    print("辅助决策：预算 → 城市底线推移")
    print("=" * 60)

    # 基线底线（无干预）
    baseline = bottom_line_with_gain(0.0, 0.0)
    print(f"基线底线（无干预）: M{baseline}")

    budgets = [round(b, 1) for b in [x / 2 for x in range(0, 21)]]  # 0~10亿
    curve = []
    for b in budgets:
        r, m = intervention(b)
        gain_m = MED_GAIN_ROAD_FULL * (r / MAX_ROADS) + MED_GAIN_POINT * m
        gain_r = RES_GAIN_ROAD_FULL * (r / MAX_ROADS)
        bl = bottom_line_with_gain(gain_m, gain_r)
        curve.append({
            "budget": b,
            "roads": r,
            "med_points": m,
            "cost": round(r * COST_ROAD_YI + m * COST_MED_YI, 2),
            "gain_medical": round(gain_m, 4),
            "gain_rescue": round(gain_r, 4),
            "bottom_line_mag": bl,
            "shift": round(bl - baseline, 1),
        })

    # 关键节点：底线被推高的最小预算 / 每推高 0.5 级的预算
    first_shift = next((c for c in curve if c["shift"] > 0), None)
    milestones = []
    target = baseline + 0.5
    while target <= 8.0:
        hit = next((c for c in curve if c["bottom_line_mag"] >= target), None)
        if hit:
            milestones.append({"target_mag": round(target, 1), "budget": hit["budget"], "roads": hit["roads"]})
        target += 0.5

    report = {
        "meta": {
            "module": "step26_decision_support",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "model": "预算线性分配 + 级联底线重算（一阶近似）",
            "basis": "prevention_strategy.csv（step14 实际推演）+ collapse_threshold.csv（step10）",
            "note": "干预提升量按加固路段线性分摊且与震级无关（保守）；交通/避难未直接施加干预",
        },
        "baseline": {"bottom_line_mag": baseline, "city_collapse": "M6.5 起城市崩溃"},
        "budget_curve": curve,
        "milestones": milestones,
        "highlights": {
            "first_shift_budget": first_shift["budget"] if first_shift else None,
            "first_shift_to": first_shift["bottom_line_mag"] if first_shift else None,
            "budget_to_m70": next((c["budget"] for c in curve if c["bottom_line_mag"] >= 7.0), None),
            "max_shift": max(c["shift"] for c in curve),
        },
        "interpretation": (
            f"城市崩溃底线基线 M{baseline}；"
            + (f"仅 {first_shift['budget']} 亿元预算（加固 {first_shift['roads']} 条关键路段）"
               f"即可把底线推高至 M{first_shift['bottom_line_mag']}。" if first_shift else "")
            + "预算-底线曲线为防灾预算分配提供量化决策依据：每一亿元能买来多少'底线高度'。"
        ),
    }

    out_path = DATA_DIR / "decision_support.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"已保存: {out_path}")

    print("\n预算 → 底线:")
    for c in curve:
        print(f"  {c['budget']:>4.1f}亿 (路段{c['roads']:>2}+医疗点{c['med_points']}) "
              f"→ 底线 M{c['bottom_line_mag']:.1f} (推移 {c['shift']:+.1f})")

    ok = verify(report)
    print("\n[OK] 自检通过" if ok else "\n[FAIL] 自检失败")
    return ok


def verify(report):
    """自检。"""
    reasons = []
    curve = report["budget_curve"]
    bls = [c["bottom_line_mag"] for c in curve]
    # 底线单调不减（预算越多越安全）
    if bls != sorted(bls):
        reasons.append("底线不随预算单调")
    # 底线在 [5, 8] 范围
    if not all(5.0 <= b <= 8.0 for b in bls):
        reasons.append("底线越界")
    # 基线 = 第一个点
    if curve[0]["budget"] != 0 or curve[0]["bottom_line_mag"] != report["baseline"]["bottom_line_mag"]:
        reasons.append("基线与 0 预算不一致")
    # 里程碑单调
    ms = report["milestones"]
    if len(ms) > 1 and [m["target_mag"] for m in ms] != sorted(m["target_mag"] for m in ms):
        reasons.append("里程碑不单调")
    for r in reasons:
        print(f"  [FAIL] {r}")
    return len(reasons) == 0


if __name__ == "__main__":
    main()
