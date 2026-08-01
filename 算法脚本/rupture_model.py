"""
rupture_model.py — 地震破裂带参数模型

基于 Wells & Coppersmith 1994 经验关系，计算破裂带宽度、长度、位移量。
用于道路阻断判定中的破裂带宽度动态计算。

参考文献：
  Wells, D.L., Coppersmith, K.J., 1994.
  New empirical relationships among magnitude, rupture length,
  rupture width, rupture area, and surface displacement.
  Bulletin of the Seismological Society of America, 84(4):974-1002.

旧版简化公式 W = 10^(M-4) 保留作对比。
"""
import numpy as np
from config_loader import get_config


class RuptureModel:
    """地震破裂带参数经验模型。"""

    def __init__(self):
        cfg = get_config()
        self.model_name = cfg.get("rupture", "model", default="wells_coppersmith_1994")
        self.params = cfg.get("rupture", "wells_coppersmith_1994", default={})
        self.fault_type = "strike_slip"  # 郯庐断裂带为走滑型

    def rupture_width(self, magnitude, fault_type=None):
        """计算破裂带宽度（km）。

        Wells & Coppersmith 1994:
          log10(W) = a + b*M  →  W = 10^(a + b*M)

        走滑断层：a=-1.01, b=0.32
        旧版简化：W = 10^(M-4)

        Args:
            magnitude: 震级 M
            fault_type: 断层类型 (strike_slip/reverse/normal)

        Returns:
            破裂带宽度 (km)
        """
        M = float(magnitude)
        ft = fault_type or self.fault_type
        ft_params = self.params.get(ft, self.params.get("strike_slip", {}))

        a = ft_params.get("width_a", -1.01)
        b = ft_params.get("width_b", 0.32)

        log_w = a + b * M
        width_km = 10 ** log_w
        return round(width_km, 4)

    def rupture_width_meters(self, magnitude, fault_type=None):
        """破裂带宽度（米）。"""
        return self.rupture_width(magnitude, fault_type) * 1000

    def rupture_length(self, magnitude, fault_type=None):
        """计算破裂带长度（km）。

        Wells & Coppersmith 1994:
          log10(L) = a + b*M  →  L = 10^(a + b*M)

        走滑断层：a=-3.42, b=0.89
        """
        M = float(magnitude)
        ft = fault_type or self.fault_type
        ft_params = self.params.get(ft, self.params.get("strike_slip", {}))

        a = ft_params.get("length_a", -3.42)
        b = ft_params.get("length_b", 0.89)

        log_l = a + b * M
        length_km = 10 ** log_l
        return round(length_km, 4)

    def surface_displacement(self, magnitude, fault_type=None):
        """计算地表最大位移量（m）。

        Wells & Coppersmith 1994:
          log10(D) = a + b*M  →  D = 10^(a + b*M)

        走滑断层：a=-5.46, b=0.74
        """
        M = float(magnitude)
        ft = fault_type or self.fault_type
        ft_params = self.params.get(ft, self.params.get("strike_slip", {}))

        a = ft_params.get("displacement_a", -5.46)
        b = ft_params.get("displacement_b", 0.74)

        log_d = a + b * M
        displacement_m = 10 ** log_d
        return round(displacement_m, 4)

    def legacy_width(self, magnitude):
        """旧版简化公式：W = 10^(M-4)（保留对比）。"""
        return round(10 ** (float(magnitude) - 4), 4)

    def compare_with_legacy(self, magnitude):
        """新旧模型对比。"""
        return {
            "wells_coppersmith": self.rupture_width(magnitude),
            "legacy": self.legacy_width(magnitude),
            "ratio": self.rupture_width(magnitude) / max(self.legacy_width(magnitude), 0.001),
        }

    def full_parameters(self, magnitude, fault_type=None):
        """返回完整破裂参数。"""
        return {
            "magnitude": float(magnitude),
            "fault_type": fault_type or self.fault_type,
            "width_km": self.rupture_width(magnitude, fault_type),
            "width_m": self.rupture_width_meters(magnitude, fault_type),
            "length_km": self.rupture_length(magnitude, fault_type),
            "displacement_m": self.surface_displacement(magnitude, fault_type),
            "reference": "Wells & Coppersmith, 1994, BSSA 84(4):974-1002",
        }


if __name__ == "__main__":
    print("=" * 70)
    print("破裂带参数模型对比 (Wells & Coppersmith 1994 vs 旧版)")
    print("参考: Wells, D.L., Coppersmith, K.J., 1994, BSSA 84(4):974-1002")
    print("=" * 70)

    rm = RuptureModel()

    print(f"\n{'震级':>6} | {'W&C宽度(km)':>14} {'旧版(km)':>12} {'比率':>8} | "
          f"{'长度(km)':>10} {'位移(m)':>10}")
    print("-" * 75)
    for M in [5.0, 5.5, 6.0, 6.5, 7.0, 7.5, 8.0]:
        w_wc = rm.rupture_width(M)
        w_old = rm.legacy_width(M)
        ratio = w_wc / max(w_old, 0.001)
        length = rm.rupture_length(M)
        disp = rm.surface_displacement(M)
        print(f"M{M:<5.1f} | {w_wc:>14.4f} {w_old:>12.4f} {ratio:>8.2f} | "
              f"{length:>10.4f} {disp:>10.4f}")

    # 验证
    assert rm.rupture_width(7.0) > rm.rupture_width(6.0), "宽度应随震级递增"
    assert rm.rupture_width(7.5) < 50, "M7.5 走滑断层宽度应 < 50km"
    print("\n[OK] 验证通过")

    print("\n完整参数示例 (M7.0):")
    import json
    print(json.dumps(rm.full_parameters(7.0), indent=2, ensure_ascii=False))
