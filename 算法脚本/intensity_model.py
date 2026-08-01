"""
intensity_model.py — 地震烈度衰减模型

支持多模型切换：
  1. yu2013（主模型）：俞言祥 2013 中国分区地震动衰减关系
     用于 GB18306-2015 国家地震动参数区划图
     参考：俞言祥, 2013, 中国分区地震动衰减关系的确定, 震灾防御技术
  2. simple（对比模型）：项目早期简化点源模型 I = 0.5 + 1.5M - ln(R+5)
  3. gb18306：GB18306-2015 场地修正

衰减关系形式：
  yu2013:  I = c1 + c2*M - c3*ln(R + c4*exp(c5*M))
  simple:  I = intercept + magnitude_coef*M - distance_coef*ln(R + distance_offset)

其中 R 为震中距(km)，M 为面波震级，I 为修正麦卡利烈度(MMI)。
"""
import numpy as np
from config_loader import get_config


class IntensityModel:
    """地震烈度衰减模型，支持多模型切换和对比。"""

    def __init__(self, model_name=None):
        cfg = get_config()
        self.model_name = model_name or cfg.get("intensity", "model", default="yu2013")
        self.params = cfg.get("intensity", self.model_name, default={})
        self.reference = self.params.get("reference", "")

    def compute(self, magnitude, distance_km, site_type="default"):
        """计算指定距离处的地震烈度。

        Args:
            magnitude: 面波震级 M
            distance_km: 震中距 R (km)
            site_type: 场地类型 (default/soft_soil/hard_rock)

        Returns:
            烈度值 (MMI浮点数)
        """
        M = float(magnitude)
        R = np.maximum(float(distance_km), 0.1)  # 避免 log(0)

        if self.model_name == "yu2013":
            intensity = self._yu2013(M, R)
        elif self.model_name == "simple":
            intensity = self._simple(M, R)
        elif self.model_name == "gb18306":
            intensity = self._yu2013(M, R)
            intensity += self._site_correction(site_type)
        else:
            intensity = self._yu2013(M, R)

        return round(float(intensity), 3)

    def _yu2013(self, M, R):
        """俞言祥 2013 中国东部地区衰减关系。

        I = c1 + c2*M - c3*ln(R + c4*exp(c5*M))
        """
        c1 = self.params.get("c1", 1.785)
        c2 = self.params.get("c2", 1.352)
        c3 = self.params.get("c3", 1.038)
        c4 = self.params.get("c4", 0.017)
        c5 = self.params.get("c5", 0.494)

        # 近场饱和修正项
        R_sat = R + c4 * np.exp(c5 * M)
        intensity = c1 + c2 * M - c3 * np.log(R_sat)

        return intensity

    def _simple(self, M, R):
        """旧版简化点源模型（保留作对比）。

        I = intercept + magnitude_coef*M - distance_coef*ln(R + distance_offset)
        """
        intercept = self.params.get("intercept", 0.5)
        mag_coef = self.params.get("magnitude_coef", 1.5)
        dist_coef = self.params.get("distance_coef", 1.0)
        dist_offset = self.params.get("distance_offset", 5.0)

        intensity = intercept + mag_coef * M - dist_coef * np.log(R + dist_offset)
        return intensity

    def _site_correction(self, site_type):
        """GB18306 场地 amplification 修正。"""
        cfg = get_config()
        corrections = cfg.get("intensity", "gb18306", "site_amplification",
                              default={"default": 0.0})
        return corrections.get(site_type, corrections.get("default", 0.0))

    def compute_field(self, magnitude, distances_km, site_type="default"):
        """批量计算烈度场。

        Args:
            magnitude: 震级
            distances_km: 距离数组 (km)
            site_type: 场地类型

        Returns:
            烈度数组
        """
        return np.array([
            self.compute(magnitude, d, site_type) for d in distances_km
        ])

    def compare_models(self, magnitude, distance_km):
        """多模型对比——返回所有模型的烈度计算结果。

        用于敏感性分析和模型对比展示。
        """
        results = {}
        for model_name in ["yu2013", "simple"]:
            model = IntensityModel(model_name)
            results[model_name] = model.compute(magnitude, distance_km)
        return results

    def intensity_to_grade(self, intensity):
        """将烈度浮点值转为罗马数字等级。"""
        if intensity < 4.5:
            return "IV"
        elif intensity < 5.5:
            return "V"
        elif intensity < 6.5:
            return "VI"
        elif intensity < 7.5:
            return "VII"
        elif intensity < 8.5:
            return "VIII"
        elif intensity < 9.5:
            return "IX"
        elif intensity < 10.5:
            return "X"
        elif intensity < 11.5:
            return "XI"
        else:
            return "XII"

    def info(self):
        """返回模型信息（用于文档和日志）。"""
        return {
            "model": self.model_name,
            "reference": self.reference,
            "params": {k: v for k, v in self.params.items()
                       if k not in ("reference", "region")},
        }


if __name__ == "__main__":
    # 自测：对比新旧模型在不同震级和距离下的烈度
    print("=" * 70)
    print("烈度衰减模型对比")
    print("=" * 70)

    yu = IntensityModel("yu2013")
    simple = IntensityModel("simple")

    print(f"\n俞言祥2013 参考: {yu.reference}")
    print(f"简化模型 参考: {simple.reference}")

    print(f"\n{'震级':>6} {'距离km':>8} | {'俞言祥2013':>12} {'简化模型':>12} {'差值':>8}")
    print("-" * 55)
    for M in [5.0, 5.5, 6.0, 6.5, 7.0, 7.5]:
        for R in [5, 10, 20, 30, 50, 100]:
            i_yu = yu.compute(M, R)
            i_sim = simple.compute(M, R)
            diff = i_yu - i_sim
            print(f"M{M:<5.1f} {R:>6.0f}km | {i_yu:>12.3f} {i_sim:>12.3f} {diff:>+8.3f}")
        print()

    # 验证：M7.5 在 10km 处应产生高烈度
    assert yu.compute(7.5, 10) > 8.0, "M7.5@10km 烈度应 > VIII"
    # 验证：M5.0 在 100km 处应低烈度
    assert yu.compute(5.0, 100) < 5.0, "M5.0@100km 烈度应 < V"
    print("[OK] 基本验证通过")
