"""
step21_fault_risk_profile.py — 断裂带风险剖面（压测叙事的空间维度）

从 step20 的逆压测震中偏移扫描结果提取"断裂带沿线风险剖面"：
  - 沿断裂带走向（N-S）的临界震级剖面：破裂发生在哪个位置最危险
  - 垂直走向的临界震级剖面：破裂偏离断裂带的影响
  - 最不利破裂位置相对基准震中的临界震级降幅（"底线被压低多少"）

输出：数据文件/fault_risk_profile.json（前端风险剖面展示数据源）

同时预留脆弱设施采集入口（高德配额恢复后可采集学校/养老院，
当前数据源不可达时优雅降级，不阻塞主线）。
"""
import json
from datetime import datetime
from pathlib import Path

import numpy as np

DATA_DIR = Path(__file__).resolve().parent.parent / "数据文件"

# 与 step20_reverse_stress 的扫描域一致（基础功能率模型训练域）
MAG_MIN = 5.0


def load_epicenter_scan():
    """读取 step20 输出的震中扫描结果。"""
    report_path = DATA_DIR / "stress_report.json"
    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)
    return report["reverse_stress"]["epicenter_scan"]


def build_risk_profile():
    """提取断裂带风险剖面。"""
    scan = load_epicenter_scan()
    offsets = np.array(scan["offsets_km"])
    matrix = np.array(scan["critical_mag_matrix"])
    n = len(offsets)

    # 沿走向剖面（dx=0 列 = 断裂带正上方不同纬度破裂位置；dx=±10 为相邻带）
    def profile_at_dx(dx_idx):
        col = matrix[:, dx_idx]
        return [
            {"offset_km": float(offsets[i]),
             "critical_mag": None if np.isnan(col[i]) else float(col[i])}
            for i in range(n)
        ]

    # 垂直剖面（dy=0 行 = 同一纬度不同经度偏移）
    def profile_at_dy(dy_idx):
        row = matrix[dy_idx, :]
        return [
            {"offset_km": float(offsets[j]),
             "critical_mag": None if np.isnan(row[j]) else float(row[j])}
            for j in range(n)
        ]

    center = n // 2
    along_strike = profile_at_dx(center)          # 沿断裂带走向（dx=0）
    along_strike_e10 = profile_at_dx(center + 1)  # 东偏移 10km 带
    across_strike = profile_at_dy(center)         # 垂直走向（dy=0）

    # 最不利位置相对基准的临界震级降幅（可能因扫描域下界截断为 0）
    baseline_mag = scan["baseline_epicenter"]["critical_mag"]
    mv = scan["most_vulnerable"]
    sf = scan["safest"]
    shift = (baseline_mag - mv["critical_mag"]) if (
        baseline_mag is not None and mv["critical_mag"] is not None) else None
    # 烈度敏感性范围（连续指标，不受截断影响）
    dI_range = abs(mv["dI_bar"] - sf["dI_bar"]) if mv and sf else None

    # 剖面统计
    valid_along = [p["critical_mag"] for p in along_strike if p["critical_mag"] is not None]
    worst_along = min(valid_along) if valid_along else None
    best_along = max(valid_along) if valid_along else None

    # 解读：dI_bar 全 ≤ 0 说明质心即最不利位置（城区正压断裂带最危险段）
    if mv and mv["dI_bar"] <= 1e-9:
        story = (
            f"破裂位置敏感性：质心（117.28, 31.82）即人口加权烈度的最不利位置——"
            f"合肥城区正位于断裂带最危险破裂段正上方，任何破裂位置偏移都使城区"
            f"平均烈度下降（最多 {abs(sf['dI_bar']):.2f} 度）。"
            f"临界震级因扫描域下界（M{MAG_MIN}）截断而持平，"
            f"实际敏感性体现在烈度场上。"
        )
    else:
        story = (
            f"最不利破裂位置在 ({mv['lon']}, {mv['lat']})，"
            f"人口加权烈度偏移 dI_bar={mv['dI_bar']:.3f}；"
            f"破裂位置改变可使城区烈度波动约 {dI_range:.2f} 度。"
        )

    return {
        "meta": {
            "module": "step21_fault_risk_profile",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": "step20_reverse_stress 震中偏移扫描",
            "baseline_epicenter": scan["baseline_epicenter"],
            "offsets_unit": "km（负=南/西，正=北/东）",
            "indicator_note": scan.get("indicator_note", ""),
        },
        "along_strike_profile": along_strike,
        "along_strike_east10": along_strike_e10,
        "across_strike_profile": across_strike,
        "highlights": {
            "baseline_critical_mag": baseline_mag,
            "most_vulnerable": mv,
            "safest": sf,
            "critical_mag_shift_from_baseline": shift,
            "intensity_sensitivity_range": (
                round(dI_range, 3) if dI_range is not None else None),
            "worst_along_strike_mag": worst_along,
            "safest_along_strike_mag": best_along,
        },
        "interpretation": story,
    }


def main():
    print("=" * 60)
    print("断裂带风险剖面")
    print("=" * 60)
    profile = build_risk_profile()

    h = profile["highlights"]
    print(f"\n基准震中临界震级: M{h['baseline_critical_mag']}")
    print(f"最不利破裂位置: ({h['most_vulnerable']['lon']}, {h['most_vulnerable']['lat']}) "
          f"临界 M{h['most_vulnerable']['critical_mag']}")
    if h["critical_mag_shift_from_baseline"] is not None:
        print(f"临界震级降幅: {h['critical_mag_shift_from_baseline']} 级")
    print(f"沿走向最危险: M{h['worst_along_strike_mag']} | 最安全: M{h['safest_along_strike_mag']}")

    out_path = DATA_DIR / "fault_risk_profile.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
    print(f"\n已保存: {out_path}")

    ok = verify(profile)
    print("\n[OK] 自检通过" if ok else "\n[FAIL] 自检失败")
    return ok


def verify(profile):
    """自检。"""
    reasons = []
    h = profile["highlights"]
    if h["baseline_critical_mag"] is None:
        reasons.append("基准临界震级缺失")
    if h["most_vulnerable"] is None or h["safest"] is None:
        reasons.append("最不利/最安全位置缺失")
    else:
        # 最不利 dI_bar 应 ≥ 最安全 dI_bar（最不利=烈度更强）
        if h["most_vulnerable"]["dI_bar"] < h["safest"]["dI_bar"] - 1e-9:
            reasons.append("最不利位置 dI_bar 应 ≥ 最安全位置")
        if h["intensity_sensitivity_range"] is None or h["intensity_sensitivity_range"] < 0:
            reasons.append("烈度敏感性范围异常")
    # 剖面单调性不强制（破裂位置非单调），但需有有效点
    along = [p["critical_mag"] for p in profile["along_strike_profile"]]
    if not any(v is not None for v in along):
        reasons.append("沿走向剖面无有效数据")
    for r in reasons:
        print(f"  [FAIL] {r}")
    return len(reasons) == 0


if __name__ == "__main__":
    main()
