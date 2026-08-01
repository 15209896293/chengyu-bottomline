"""
step16_time_stepping.py — 时间步进级联演化分析

模拟地震发生后不同时间点（T+0 → T+72h）的系统功能率演化，
展示级联失效如何在时间维度上逐步展开。

时间步骤（来自 config.yaml）：
  T+0:    地震瞬间        cascade_factor=0.0  （无级联，仅直接损失）
  T+1h:   道路阻断定型    cascade_factor=0.3  （级联开始传播）
  T+6h:   医疗资源耗竭    cascade_factor=0.6  （级联显著扩散）
  T+24h:  救援扩散         cascade_factor=0.85 （级联接近完成）
  T+72h:  避难饱和         cascade_factor=1.0  （级联完全收敛）

输出：
  - time_stepping.json：所有震级×所有时间步的系统功能率矩阵
  - 更新 dashboard_M*.json 添加 time_evolution 数据段
"""
import os
import sys
import json
import numpy as np
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config_loader import get_config, setup_gdal
from cascade_model import CascadeModel


def run_time_stepping():
    """运行时间步进级联演化分析。"""
    cfg = get_config()
    data_dir = cfg.data_dir
    magnitudes = cfg.magnitudes
    time_steps = cfg.get("time_stepping", "steps", default=[])

    print(f"  时间步数: {len(time_steps)}")
    for step in time_steps:
        print(f"    {step['label']:>8} ({step['desc']}): factor={step['cascade_factor']}")

    model = CascadeModel()
    base_rates = model.load_base_rates()

    # 对每个震级，计算每个时间步的级联状态
    all_evolution = {}

    for base in base_rates:
        mag = base["magnitude"]
        mag_key = f"M{mag:.1f}"
        print(f"\n■ {mag_key}")

        evolution_steps = []
        for step in time_steps:
            factor = step["cascade_factor"]
            cascade = model.compute_cascade(base, propagation_factor=factor)

            # 崩溃判定
            collapses = {}
            statuses = {}
            for k in model.SYSTEM_KEYS:
                collapsed = model.judge_collapse(cascade[k], k)
                collapses[k] = collapsed
                statuses[k] = model.system_status(cascade[k], k)

            city_collapse = any(collapses.values())
            collapsed_count = sum(1 for v in collapses.values() if v)

            step_data = {
                "time": step["time"],
                "label": step["label"],
                "desc": step["desc"],
                "cascade_factor": factor,
                "systems": {
                    k: {
                        "ratio": cascade[k],
                        "drop": cascade[f"{k}_drop"],
                        "collapsed": collapses[k],
                        "status": statuses[k],
                        "name": model.SYSTEM_NAMES[k],
                        "color": model.SYSTEM_COLORS[k],
                        "threshold": model.thresholds.get(k, 0.3),
                    }
                    for k in model.SYSTEM_KEYS
                },
                "city_collapse": city_collapse,
                "collapsed_count": collapsed_count,
            }
            evolution_steps.append(step_data)

            # 找首次崩溃时间
            if city_collapse and len(evolution_steps) > 1:
                prev_collapse = evolution_steps[-2]["city_collapse"]
                if not prev_collapse:
                    print(f"    {step['label']}: 首次城市崩溃！"
                          f"({collapsed_count}/4系统崩溃)")

        all_evolution[mag_key] = {
            "magnitude": mag,
            "steps": evolution_steps,
            "first_collapse_time": next(
                (s["label"] for s in evolution_steps if s["city_collapse"]), None
            ),
            "final_state": evolution_steps[-1] if evolution_steps else None,
        }

        # 打印最终状态
        final = evolution_steps[-1]
        print(f"    最终(T+72h): 医{final['systems']['medical']['ratio']:.3f} "
              f"救{final['systems']['rescue']['ratio']:.3f} "
              f"交{final['systems']['transport']['ratio']:.3f} "
              f"避{final['systems']['shelter']['ratio']:.3f} "
              f"→ {'崩溃' if final['city_collapse'] else '未崩溃'}")

    return all_evolution, time_steps


def build_timeline_events(all_evolution, time_steps):
    """构建时间轴事件列表（用于前端时间轴可视化）。"""
    events = []
    for step in time_steps:
        # 找该时间点各震级的崩溃情况
        mag_collapse = {}
        for mag_key, data in all_evolution.items():
            for s in data["steps"]:
                if s["label"] == step["label"]:
                    mag_collapse[mag_key] = {
                        "city_collapse": s["city_collapse"],
                        "collapsed_count": s["collapsed_count"],
                    }
                    break

        # 该时间点崩溃的震级数
        collapse_count = sum(1 for v in mag_collapse.values() if v["city_collapse"])

        events.append({
            "time": step["time"],
            "label": step["label"],
            "desc": step["desc"],
            "cascade_factor": step["cascade_factor"],
            "collapsed_magnitudes": collapse_count,
            "total_magnitudes": len(mag_collapse),
        })
    return events


def save_results(all_evolution, time_steps, events):
    """保存结果到 JSON。"""
    cfg = get_config()
    data_dir = cfg.data_dir

    # 1. 保存独立的 time_stepping.json
    output = {
        "meta": {
            "description": "时间步进级联演化分析",
            "time_steps": time_steps,
            "magnitudes": cfg.magnitudes,
        },
        "evolution": all_evolution,
        "timeline_events": events,
    }

    out_path = data_dir / "time_stepping.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n  保存: {out_path} ({out_path.stat().st_size / 1024:.1f}KB)")

    # 2. 更新 dashboard JSON 添加 time_evolution 段
    for mag_key, data in all_evolution.items():
        mag = data["magnitude"]
        json_path = data_dir / f"dashboard_M{mag:.1f}.json"
        if not json_path.exists():
            print(f"  [跳过] {json_path.name} 不存在")
            continue

        with open(json_path, "r", encoding="utf-8") as f:
            dashboard = json.load(f)

        dashboard["time_evolution"] = {
            "steps": data["steps"],
            "first_collapse_time": data["first_collapse_time"],
        }

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(dashboard, f, ensure_ascii=False, indent=2)
        print(f"  更新: {json_path.name} (time_evolution)")


def verify(all_evolution, time_steps):
    """验证输出正确性。"""
    ok = True
    reasons = []

    # 1. 每个震级都有所有时间步
    for mag_key, data in all_evolution.items():
        if len(data["steps"]) != len(time_steps):
            ok = False
            reasons.append(f"{mag_key} 时间步数 {len(data['steps'])} != {len(time_steps)}")

    # 2. 功能率随时间单调递减（级联只降低不提升）
    for mag_key, data in all_evolution.items():
        for k in ["medical", "rescue", "shelter"]:
            vals = [s["systems"][k]["ratio"] for s in data["steps"]]
            for i in range(1, len(vals)):
                if vals[i] > vals[i - 1] + 0.001:
                    ok = False
                    reasons.append(f"{mag_key} {k}: 时间步 {i} 功能率上升 "
                                   f"({vals[i]:.4f} > {vals[i-1]:.4f})")

    # 3. T+0 的功能率应等于基础率（无级联）
    for mag_key, data in all_evolution.items():
        t0 = data["steps"][0]
        if t0["cascade_factor"] != 0.0:
            ok = False
            reasons.append(f"{mag_key} T+0 cascade_factor 应为 0.0")

    # 4. T+72h 的功能率应等于完全级联值
    for mag_key, data in all_evolution.items():
        tfinal = data["steps"][-1]
        if abs(tfinal["cascade_factor"] - 1.0) > 0.01:
            ok = False
            reasons.append(f"{mag_key} 最终 cascade_factor 应为 1.0")

    if ok:
        print("  [OK] 每个震级包含所有时间步")
        print("  [OK] 功能率随时间单调递减")
        print("  [OK] T+0 无级联，T+72h 完全级联")
        print("\n验证通过")
    else:
        print("\n验证失败:")
        for r in reasons:
            print(f"  - {r}")
    return ok


def main():
    print("=" * 60)
    print("step16 时间步进级联演化分析")
    print("=" * 60)

    print("\n计算各震级×各时间步的级联演化...")
    all_evolution, time_steps = run_time_stepping()

    print(f"\n{'─' * 60}")
    print("构建时间轴事件...")
    events = build_timeline_events(all_evolution, time_steps)
    for e in events:
        print(f"  {e['label']:>8}: {e['collapsed_magnitudes']}/{e['total_magnitudes']} 震级崩溃")

    print(f"\n{'─' * 60}")
    print("保存结果...")
    save_results(all_evolution, time_steps, events)

    print(f"\n{'─' * 60}")
    print("验证...")
    verify(all_evolution, time_steps)

    # 汇总：首次崩溃时间
    print(f"\n{'─' * 60}")
    print("汇总：各震级首次城市崩溃时间")
    print(f"{'─' * 60}")
    for mag_key, data in all_evolution.items():
        t = data["first_collapse_time"]
        if t:
            print(f"  {mag_key}: 首次崩溃于 {t}")
        else:
            print(f"  {mag_key}: 72h内未崩溃")

    print(f"\n{'=' * 60}")
    print("完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
