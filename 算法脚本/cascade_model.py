"""
cascade_model.py — 迭代传播级联模型（核心创新）

将 step10（独立崩溃阈值）和 step15（线性级联叠加）合并为统一耦合计算。

核心升级：
  1. 旧版 step15 是单次线性传播（交通→医疗→救援→避难，无反馈）
  2. 新版用迭代传播：医疗变化反馈影响救援，救援变化再反馈影响医疗……
     迭代到收敛，处理循环依赖
  3. 收敛后的级联功能率直接用于崩溃阈值判定（不再"各算各的"）
  4. 支持部分传播因子（用于时间步进推演）
  5. 支持参数覆盖（用于蒙特卡洛敏感性分析）

传播模型：
  对每个系统 target，级联后功能率 =
    base_target × Π (1 - dep[target][source] × (1 - cascade[source]))

  交通系统是根因（地震→路网阻断），不受其他系统级联影响。

参考文献：
  Haimes, Y.Y., Jiang, P., 2001. Leontief-based model of risk in complex
  interconnected infrastructures. Journal of Infrastructure Systems, 7(1):1-12.
"""
import json
import numpy as np
import pandas as pd
from pathlib import Path
from config_loader import get_config


class CascadeModel:
    """迭代传播级联模型。"""

    SYSTEM_KEYS = ["medical", "transport", "rescue", "shelter"]
    SYSTEM_NAMES = {"medical": "医疗", "transport": "交通",
                    "rescue": "救援", "shelter": "避难"}
    SYSTEM_LABELS = ["医", "交", "救", "避"]
    SYSTEM_COLORS = {"medical": "#F87171", "transport": "#FBBF24",
                     "rescue": "#FB923C", "shelter": "#34D399"}

    def __init__(self, params_override=None):
        """初始化级联模型。

        Args:
            params_override: 参数覆盖字典（用于敏感性分析），
                             如 {"dependency_matrix": {...}, "thresholds": {...}}
        """
        cfg = get_config()

        # 依赖矩阵
        if params_override and "dependency_matrix" in params_override:
            self.dep = params_override["dependency_matrix"]
        else:
            self.dep = cfg.get("cascade", "dependency_matrix", default={})

        # 崩溃阈值
        if params_override and "thresholds" in params_override:
            self.thresholds = params_override["thresholds"]
        else:
            self.thresholds = cfg.get("collapse_thresholds", default={})

        # 迭代控制
        self.max_iterations = cfg.get("cascade", "max_iterations", default=100)
        self.tolerance = cfg.get("cascade", "convergence_tolerance", default=0.0001)

        # 数据目录
        self.data_dir = cfg.data_dir

    def compute_cascade(self, base_rates, propagation_factor=1.0):
        """迭代计算级联传播后的功能率。

        核心算法：迭代传播直到收敛。
        propagation_factor 控制级联传播完成比例：
          0.0 = 无级联（cascade = base）
          1.0 = 完全级联（收敛值）
          0.5 = 半传播（base 和收敛值的中点）

        Args:
            base_rates: dict {medical, transport, rescue, shelter} 基础功能率
            propagation_factor: 传播完成比例 [0, 1]

        Returns:
            dict: 级联后功能率 + 传播信息
        """
        # 先计算完全收敛的级联
        full_cascade = self._iterate_to_convergence(base_rates)

        # 按传播因子插值
        if propagation_factor >= 1.0:
            cascade = full_cascade
        elif propagation_factor <= 0.0:
            cascade = {k: base_rates[k] for k in self.SYSTEM_KEYS}
        else:
            cascade = {}
            for k in self.SYSTEM_KEYS:
                cascade[k] = (base_rates[k]
                              + (full_cascade[k] - base_rates[k]) * propagation_factor)

        # 计算各系统级联下降量
        drops = {}
        for k in self.SYSTEM_KEYS:
            drops[k] = round(base_rates[k] - cascade[k], 4)

        return {
            "medical": round(max(0.0, cascade["medical"]), 4),
            "transport": round(max(0.0, cascade["transport"]), 4),
            "rescue": round(max(0.0, cascade["rescue"]), 4),
            "shelter": round(max(0.0, cascade["shelter"]), 4),
            "medical_drop": drops["medical"],
            "transport_drop": 0.0,  # 交通是根因
            "rescue_drop": drops["rescue"],
            "shelter_drop": drops["shelter"],
            "propagation_factor": propagation_factor,
            "converged": full_cascade,
        }

    def _iterate_to_convergence(self, base_rates):
        """迭代传播直到收敛。

        迭代步骤：
          1. 初始化 cascade = base_rates
          2. 循环更新每个系统的级联功能率
          3. 检查收敛（最大变化 < tolerance）
        """
        cascade = {k: base_rates[k] for k in self.SYSTEM_KEYS}

        for iteration in range(self.max_iterations):
            prev = cascade.copy()

            # 交通系统是根因，不受级联影响
            cascade["transport"] = base_rates["transport"]

            # 计算各系统损失度
            t_loss = 1.0 - cascade["transport"]
            m_loss = 1.0 - cascade["medical"]
            r_loss = 1.0 - cascade["rescue"]

            # 医疗：受交通 + 救援影响
            dep_t_m = self.dep.get("medical", {}).get("transport", 0.0)
            dep_r_m = self.dep.get("medical", {}).get("rescue", 0.0)
            cascade["medical"] = max(0.0, base_rates["medical"]
                                     * (1.0 - dep_t_m * t_loss)
                                     * (1.0 - dep_r_m * r_loss))

            # 救援：受交通 + 医疗影响
            dep_t_r = self.dep.get("rescue", {}).get("transport", 0.0)
            dep_m_r = self.dep.get("rescue", {}).get("medical", 0.0)
            cascade["rescue"] = max(0.0, base_rates["rescue"]
                                    * (1.0 - dep_t_r * t_loss)
                                    * (1.0 - dep_m_r * m_loss))

            # 避难：受医疗 + 救援 + 交通影响
            dep_m_s = self.dep.get("shelter", {}).get("medical", 0.0)
            dep_r_s = self.dep.get("shelter", {}).get("rescue", 0.0)
            dep_t_s = self.dep.get("shelter", {}).get("transport", 0.0)
            cascade["shelter"] = max(0.0, base_rates["shelter"]
                                     * (1.0 - dep_m_s * m_loss)
                                     * (1.0 - dep_r_s * r_loss)
                                     * (1.0 - dep_t_s * t_loss))

            # 收敛检查
            max_change = max(abs(cascade[k] - prev[k]) for k in self.SYSTEM_KEYS)
            if max_change < self.tolerance:
                break

        return cascade

    def judge_collapse(self, ratio, system_key):
        """判定系统是否崩溃。"""
        threshold = self.thresholds.get(system_key, 0.3)
        return ratio < threshold

    def city_collapsed(self, cascade):
        """城市是否崩溃（任一系统崩溃）。"""
        return any(
            self.judge_collapse(cascade[k], k)
            for k in self.SYSTEM_KEYS
        )

    def find_threshold_magnitude(self, all_results):
        """找到城市崩溃临界震级。

        Args:
            all_results: list of {magnitude, cascade} 按震级升序

        Returns:
            临界震级 or None
        """
        for result in all_results:
            if self.city_collapsed(result["cascade"]):
                return result["magnitude"]
        return None

    def system_status(self, ratio, system_key):
        """返回系统状态标签。"""
        threshold = self.thresholds.get(system_key, 0.3)
        collapsed = ratio < threshold
        if collapsed:
            return "已崩溃"
        if ratio < threshold * 1.2:
            return "级联风险"
        if ratio < threshold * 1.5:
            return "承压"
        return "正常"

    def load_base_rates(self):
        """从 collapse_threshold.csv 加载基础功能率。"""
        path = self.data_dir / "collapse_threshold.csv"
        df = pd.read_csv(path, encoding="utf-8-sig")
        df["magnitude"] = df["magnitude"].astype(float)

        rates = []
        for _, row in df.iterrows():
            mag = float(row["magnitude"])
            med = float(row["medical_ratio"])
            res = float(row["rescue_ratio"])
            tr = float(row["transport_ratio"])
            sh = min(float(row["shelter_ratio"]), 1.0)  # 封顶
            rates.append({
                "magnitude": mag,
                "medical": med,
                "rescue": res,
                "transport": tr,
                "shelter": sh,
            })
        return rates

    def compute_all_magnitudes(self, propagation_factor=1.0):
        """计算所有震级的级联结果。

        Returns:
            list of {magnitude, base, cascade}
        """
        base_rates = self.load_base_rates()
        results = []
        for base in base_rates:
            cascade = self.compute_cascade(base, propagation_factor)
            results.append({
                "magnitude": base["magnitude"],
                "base": base,
                "cascade": cascade,
            })
        return results

    def compare_independent_vs_cascade(self):
        """对比独立评估 vs 级联耦合评估。

        这是答辩时的关键证据：展示级联如何改变崩溃结论。
        """
        results = self.compute_all_magnitudes()

        comparison = []
        for r in results:
            mag = r["magnitude"]
            base = r["base"]
            cascade = r["cascade"]

            # 独立评估崩溃判定
            independent_collapses = {
                k: self.judge_collapse(base[k], k) for k in self.SYSTEM_KEYS
            }
            independent_city = any(independent_collapses.values())

            # 级联耦合崩溃判定
            cascade_collapses = {
                k: self.judge_collapse(cascade[k], k) for k in self.SYSTEM_KEYS
            }
            cascade_city = any(cascade_collapses.values())

            comparison.append({
                "magnitude": mag,
                "independent": {
                    "medical": base["medical"],
                    "rescue": base["rescue"],
                    "transport": base["transport"],
                    "shelter": base["shelter"],
                    "city_collapse": independent_city,
                    "collapses": independent_collapses,
                },
                "cascade": {
                    "medical": cascade["medical"],
                    "rescue": cascade["rescue"],
                    "transport": cascade["transport"],
                    "shelter": cascade["shelter"],
                    "city_collapse": cascade_city,
                    "collapses": cascade_collapses,
                },
                "drop": {
                    "medical": cascade["medical_drop"],
                    "rescue": cascade["rescue_drop"],
                    "shelter": cascade["shelter_drop"],
                },
            })

        return comparison

    def build_propagation_paths(self, cascade, base):
        """构建级联传播路径列表（用于前端可视化）。"""
        paths = []
        descriptions = get_config().get("cascade", "descriptions", default={})

        for target in self.SYSTEM_KEYS:
            for source in self.SYSTEM_KEYS:
                if source == target:
                    continue
                weight = self.dep.get(target, {}).get(source, 0.0)
                if weight <= 0.0:
                    continue
                source_drop = base[source] - cascade[source]
                propagated_drop = round(source_drop * weight, 4)
                paths.append({
                    "source": source,
                    "target": target,
                    "weight": weight,
                    "source_ratio": cascade[source],
                    "source_drop": round(source_drop, 4),
                    "propagated_drop": propagated_drop,
                    "description": descriptions.get(
                        f"{source},{target}",
                        f"{self.SYSTEM_NAMES[source]}→{self.SYSTEM_NAMES[target]} 依赖传播"
                    ),
                })
        return paths

    def build_cascade_timeline(self, cascade, base, mag):
        """构建级联传播时间线。"""
        return [
            {"step": 0, "event": "交通系统受损", "system": "transport",
             "ratio": cascade["transport"], "drop": 1.0 - cascade["transport"],
             "description": f"M{mag:.1f} 地震导致路网阻断"},
            {"step": 1, "event": "医疗系统受波及", "system": "medical",
             "ratio": cascade["medical"], "drop": cascade["medical_drop"],
             "description": "路网阻断导致医院可达性下降，医疗物资运输中断"},
            {"step": 2, "event": "救援系统受波及", "system": "rescue",
             "ratio": cascade["rescue"], "drop": cascade["rescue_drop"],
             "description": "路网阻断导致消防站出勤受限，救援转运能力下降"},
            {"step": 3, "event": "避难系统受波及", "system": "shelter",
             "ratio": cascade["shelter"], "drop": cascade["shelter_drop"],
             "description": "医疗和救援功能下降影响避难所伤员救治与安全保障"},
        ]

    def build_vulnerable_nodes(self, all_results):
        """构建跨震级脆弱节点数据。"""
        vuln_nodes = []
        for sys_key in self.SYSTEM_KEYS:
            first_collapse_mag = None
            min_ratio = 1.0
            for result in all_results:
                ratio = result["cascade"][sys_key]
                min_ratio = min(min_ratio, ratio)
                if self.judge_collapse(ratio, sys_key) and first_collapse_mag is None:
                    first_collapse_mag = result["magnitude"]

            vulnerability = round(1.0 - min_ratio, 2)
            pct = int(vulnerability * 100)

            if first_collapse_mag is not None:
                val_str = f"{vulnerability:.2f} · M{first_collapse_mag:.1f}"
            else:
                val_str = f"{vulnerability:.2f} · 未崩溃"

            vuln_nodes.append({
                "name": f"{self.SYSTEM_NAMES[sys_key]}系统",
                "val": val_str, "pct": pct,
                "magnitude": first_collapse_mag,
                "vulnerability": vulnerability,
                "color": self.SYSTEM_COLORS[sys_key],
                "system": sys_key,
            })
        return vuln_nodes

    def get_symmetric_matrix(self):
        """返回对称依赖矩阵（前端热力图用）。"""
        cfg = get_config()
        return cfg.get("cascade", "symmetric_matrix", default=[
            [1.00, 0.45, 0.20, 0.38],
            [0.45, 1.00, 0.55, 0.20],
            [0.20, 0.55, 1.00, 0.52],
            [0.38, 0.20, 0.52, 1.00],
        ])


if __name__ == "__main__":
    print("=" * 70)
    print("迭代传播级联模型 — 独立评估 vs 级联耦合 对比")
    print("=" * 70)

    model = CascadeModel()
    comparison = model.compare_independent_vs_cascade()

    print(f"\n{'震级':>6} | {'独立评估':>30} | {'级联耦合':>30} | {'变化':>20}")
    print("-" * 95)
    for cmp in comparison:
        mag = cmp["magnitude"]
        ind = cmp["independent"]
        cas = cmp["cascade"]

        ind_str = (f"医{ind['medical']:.3f}({'崩' if ind['collapses']['medical'] else '○'}) "
                   f"救{ind['rescue']:.3f}({'崩' if ind['collapses']['rescue'] else '○'})")
        cas_str = (f"医{cas['medical']:.3f}({'崩' if cas['collapses']['medical'] else '○'}) "
                   f"救{cas['rescue']:.3f}({'崩' if cas['collapses']['rescue'] else '○'})")
        change = "→ 城市崩溃提前!" if (cas["city_collapse"] and not ind["city_collapse"]) else ""

        print(f"M{mag:<5.1f} | {ind_str:>30} | {cas_str:>30} | {change:>20}")

    # 找崩溃临界点
    ind_threshold = None
    cas_threshold = None
    for cmp in comparison:
        if cmp["independent"]["city_collapse"] and ind_threshold is None:
            ind_threshold = cmp["magnitude"]
        if cmp["cascade"]["city_collapse"] and cas_threshold is None:
            cas_threshold = cmp["magnitude"]

    print(f"\n★ 独立评估崩溃临界点: M{ind_threshold}" if ind_threshold else "\n★ 独立评估未崩溃")
    print(f"★ 级联耦合崩溃临界点: M{cas_threshold}" if cas_threshold else "★ 级联耦合未崩溃")

    if cas_threshold and ind_threshold and cas_threshold < ind_threshold:
        print(f"★ 级联效应使崩溃临界点提前了 {ind_threshold - cas_threshold} 个震级档！")
        print("  → 这证明级联耦合真正影响了结论，而非装饰性叠加。")

    # 验证
    print("\n验证:")
    results = model.compute_all_magnitudes()
    for r in results:
        for k in model.SYSTEM_KEYS:
            assert r["cascade"][k] <= r["base"][k] + 0.001, \
                f"M{r['magnitude']} {k}: 级联率不应大于基础率"
    print("  [OK] 级联功能率 <= 基础功能率")
