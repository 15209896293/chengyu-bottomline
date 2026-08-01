"""
stressor_model.py — 压力源抽象层（金融压测框架的"情景发生器"）

把"压力源"抽象为可扩展基类，地震只是第一个实现。预留暴雨/疫情等
第二压源接口——对应"多灾种通用压测框架"的架构定位。

设计：
  Stressor（基类）
    ├─ EarthquakeStressor  — 地震压源（俞言祥2013 烈度衰减 + W&C 破裂参数）
    ├─ FloodStressor       — 暴雨内涝压源（预留骨架，待内涝模型数据）
    └─ EpidemicStressor    — 疫情压源（预留骨架）

每个压源暴露统一接口：
  - name / type：标识
  - parameters：config 声明的压源参数
  - compute_intensity(magnitude, distance_km)：压源强度场（烈度/水深/感染率）
  - describe()：给答辩/文档用的一句话描述

自检：verify_earthquake() 验证 EarthquakeStressor 与现有 IntensityModel
输出一致（保证抽象层不破坏现有管线）。
"""
import json
from abc import ABC, abstractmethod

from config_loader import get_config
from intensity_model import IntensityModel


class Stressor(ABC):
    """压力源基类：所有压源实现统一接口。"""

    TYPE = "base"

    def __init__(self, name, params=None):
        self.name = name
        self.params = params or {}
        self._imodel = None

    @abstractmethod
    def compute_intensity(self, magnitude, distance_km):
        """压源强度场。地震返回烈度，暴雨返回水深(m)，疫情返回感染率。"""

    def describe(self):
        return f"{self.name}（{self.TYPE}压源）"

    def to_dict(self):
        return {"type": self.TYPE, "name": self.name, "params": self.params}


class EarthquakeStressor(Stressor):
    """地震压源：俞言祥2013 烈度衰减 + Wells & Coppersmith 破裂参数。"""

    TYPE = "earthquake"

    def __init__(self, name, params=None, intensity_model=None):
        super().__init__(name, params)
        self._imodel = intensity_model or IntensityModel()

    def compute_intensity(self, magnitude, distance_km):
        """返回烈度（MMI 浮点）。"""
        return self._imodel.compute(magnitude, distance_km)

    def intensity_field(self, magnitude, distances_km):
        """批量烈度场。"""
        return self._imodel.compute_field(magnitude, distances_km)

    def describe(self):
        return (f"{self.name}（地震压源）：俞言祥2013烈度衰减，"
                f"震中 {self.params.get('epicenter', '?')}")

    def to_dict(self):
        d = super().to_dict()
        d["attenuation_model"] = "yu2013"
        d["epicenter"] = self.params.get("epicenter")
        return d


class FloodStressor(Stressor):
    """暴雨内涝压源（预留骨架）。

    需要内涝模型数据（降水-淹没深度映射）才能实例化强度场；
    当前仅保留接口与配置位，接入时实现 compute_intensity 即可。
    """

    TYPE = "flood"

    def __init__(self, name, params=None):
        super().__init__(name, params)
        if params and params.get("depth_model"):
            raise NotImplementedError(
                "内涝淹没模型未实现：FloodStressor 需降水→水深映射数据。"
                "预留接口，接入后即可作为第二压源参与压测。")

    def compute_intensity(self, magnitude, distance_km):
        raise NotImplementedError(
            "FloodStressor.compute_intensity 未实现：需接入内涝淹没模型。")


class EpidemicStressor(Stressor):
    """疫情压源（预留骨架）。

    感染率-医疗负荷映射待数据接入；接口与 EarthquakeStressor 对齐。
    """

    TYPE = "epidemic"

    def compute_intensity(self, magnitude, distance_km):
        raise NotImplementedError(
            "EpidemicStressor.compute_intensity 未实现：需接入感染扩散模型。")


def create_stressor(stressor_type, name, params=None):
    """压源工厂。"""
    registry = {
        "earthquake": EarthquakeStressor,
        "flood": FloodStressor,
        "epidemic": EpidemicStressor,
    }
    if stressor_type not in registry:
        raise ValueError(f"未知压源类型: {stressor_type}，可用: {list(registry)}")
    return registry[stressor_type](name, params)


def load_scenario_stressors():
    """从 config.yaml multi_source/scenarios 加载现有 4 个地震震源为压源实例。"""
    cfg = get_config()
    scenarios = cfg.get("multi_source", "scenarios", default=[])
    stressors = []
    for s in scenarios:
        stressors.append(EarthquakeStressor(
            s.get("name", "未知震源"),
            {"epicenter": s.get("epicenter"), "fault": s.get("fault")},
        ))
    return stressors


def verify_earthquake():
    """验证抽象层与现有 IntensityModel 输出一致。"""
    cfg = get_config()
    base = IntensityModel()
    stressor = EarthquakeStressor("测试", intensity_model=base)
    failures = []
    for mag in [5.0, 6.0, 7.0, 7.5]:
        for dist in [5, 10, 20, 50, 100]:
            a = base.compute(mag, dist)
            b = stressor.compute_intensity(mag, dist)
            if abs(a - b) > 1e-6:
                failures.append(f"M{mag} R{dist}: {a} vs {b}")
    return failures


if __name__ == "__main__":
    print("=" * 60)
    print("压力源抽象层自检")
    print("=" * 60)

    # 1. 现有 4 震源加载
    stressors = load_scenario_stressors()
    print(f"\n现有 {len(stressors)} 个地震压源：")
    for s in stressors:
        print(f"  - {s.describe()}")

    # 2. 一致性验证
    failures = verify_earthquake()
    if failures:
        print(f"\n[FAIL] {len(failures)} 项不一致: {failures[:3]}")
    else:
        print("\n[OK] EarthquakeStressor 与 IntensityModel 输出一致")

    # 3. 多压源注册表
    print("\n压源注册表:", ", ".join([
        create_stressor("earthquake", "x").TYPE,
        create_stressor("flood", "x").TYPE,
        create_stressor("epidemic", "x").TYPE,
    ]))

    # 4. 序列化（供前端压源面板展示）
    print("\n压源 JSON 示例:")
    print(json.dumps([s.to_dict() for s in stressors], ensure_ascii=False, indent=2)[:400])
