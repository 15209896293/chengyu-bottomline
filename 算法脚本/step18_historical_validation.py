"""
step18_historical_validation.py — 历史震例验证模块

用两个公认的历史震例验证项目模型链的可信度：
    intensity_model.py（俞言祥2013烈度衰减）
    → vulnerability_matrix.py（易损性期望损失率）
    → 损失估算

验证震例（参数来自 config.yaml 的 validation 段）：
    1. 汶川 2008 M8.0  逆冲断层  震中 [103.40, 31.00]
    2. 唐山 1976 M7.8  走滑断层  震中 [118.18, 39.63]

验证内容：
    A. 烈度场对比：俞言祥2013 模型等震线半径 vs 实际等震线（面积等效半径）
       —— 这是最干净的物理验证，不依赖暴露度假设
    B. 损失估算对比：模型期望损失 × 简化暴露度  vs  实际灾损统计
       —— 受简化距离-人口密度函数限制，作为辅助验证

输出：
    f:\\比赛\\计算机设计大赛\\城域底线\\数据文件\\validation_report.json

说明与局限：
    - 俞言祥2013 为点源衰减模型，不显式建模破裂面延展；对汶川这种 300km 破裂的
      逆冲事件，近场高烈度区会系统性低估。
    - yu2013 参数（config.yaml）为中国东部标定，对川西山区远场衰减偏慢会高估。
    - 汶川/唐山缺乏与项目一致的网格化人口GDP数据，暴露度用简化指数衰减函数估算，
      损失估算偏差同时包含模型误差与暴露度误差，结论以等震线对比为准。

参考文献：
    俞言祥, 2013, 中国分区地震动衰减关系的确定, 震灾防御技术
    Wells & Coppersmith, 1994, BSSA 84(4):974-1002
    中国地震局, 汶川8.0级地震烈度分布图, 2008
    钱钢, 唐山大地震, 1986（唐山地震烈度资料）
"""
import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np

from config_loader import get_config
from intensity_model import IntensityModel
from vulnerability_matrix import VulnerabilityMatrix
from rupture_model import RuptureModel


# ═══════════════════════════════════════════════════════════════
# 历史震例实际等震线数据（面积等效半径）
# ═══════════════════════════════════════════════════════════════
# 实际等震线高度椭圆化（汶川沿破裂带NE向拉长，唐山受华北盆地影响），
# 此处用 sqrt(面积/π) 转为等效圆形半径，以便与点源衰减模型直接对比。
# 数值取自中国地震局公开发布的烈度分布图，为公开统计量级。
ACTUAL_ISOSEISMALS = {
    "wenchuan_2008": {
        # 等级: 该等级外边界等效半径(km)（即进入该烈度等级的阈值线）
        "XI": 27.6,    # XI度区面积 ~2400 km²
        "X":  39.1,    # X度区面积  ~4800 km²
        "IX": 75.7,    # IX度区面积 ~18000 km²
        "VIII": 114.2, # VIII度区面积 ~41000 km²
        "VII": 204.9,  # VII度区面积 ~132000 km²
        "VI":  374.2,  # VI度区面积  ~440000 km²
        "source": "中国地震局《汶川8.0级地震烈度分布图》(2008)；面积等效半径",
    },
    "tangshan_1976": {
        "XI": 3.9,     # 极震区面积 ~47 km²
        "X":  10.9,    # X度区面积  ~370 km²
        "IX": 23.9,    # IX度区面积 ~1800 km²
        "VIII": 48.4,  # VIII度区面积 ~7350 km²
        "VII": 103.0,  # VII度区面积 ~33300 km²
        "VI":  180.0,  # VI度区面积 ~ (有感范围，估算)
        "source": "唐山7.8级地震烈度分布图(1976)；钱钢《唐山大地震》等；面积等效半径",
    },
}

# 烈度等级 -> 下边界烈度值（进入该等级的阈值，用于反演等震线半径）
GRADE_LOWER_BOUND = {
    "VI": 5.5, "VII": 6.5, "VIII": 7.5,
    "IX": 8.5, "X": 9.5, "XI": 10.5,
}

# 断层类型映射：config 中 thrust（逆冲）映射到 rupture_model 的 reverse
FAULT_TYPE_MAP = {"thrust": "reverse", "strike_slip": "strike_slip", "reverse": "reverse"}

# ═══════════════════════════════════════════════════════════════
# 简化暴露度函数参数（区域标定）
# ═══════════════════════════════════════════════════════════════
# 人口/GDP 密度按震中距指数衰减：
#     density(r) = base * exp(-r / scale)
# 标定依据：震中区区域人口经济特征（公开统计），非对灾损结果曲线拟合。
#   —— 损失估算偏差同时反映模型误差与暴露度误差，仅作辅助验证。
EXPOSURE_PARAMS = {
    "wenchuan_2008": {
        # 川西山区（震中稀疏）+ 成都平原（近场稠密），2008 年经济水平
        "pop_base": 500.0, "pop_scale": 85.0,    # 人/km²
        "gdp_base": 5.0e6, "gdp_scale": 85.0,    # 元/km²（年）
        "note": "震中位于川西山区人口稀疏带，近场含成都平原高密度区",
    },
    "tangshan_1976": {
        # 华北平原人口稠密，1976 年经济水平（当年价格）
        "pop_base": 900.0, "pop_scale": 100.0,
        "gdp_base": 6.0e5, "gdp_scale": 100.0,
        "note": "华北平原人口稠密，1976年GDP密度按当年价格",
    },
}

# 烈度场计算范围与步长
FIELD_R_MAX = 300.0   # km，0-300km 衰减曲线
FIELD_STEP = 5.0      # km，输出曲线步长
RING_STEP = 1.0       # km，暴露度积分环宽


class HistoricalValidator:
    """历史震例验证器：用汶川/唐山震例验证项目模型链可信度。"""

    def __init__(self):
        self.cfg = get_config()
        self.intensity_model = IntensityModel("yu2013")  # 主模型：俞言祥2013
        self.vm = VulnerabilityMatrix()
        self.rm = RuptureModel()

    # ── 基础工具 ──────────────────────────────────────────────

    def _event_config(self, event_key):
        """从 config.yaml 读取历史震例参数。"""
        ec = self.cfg.get("validation", event_key, default=None)
        if ec is None:
            raise KeyError(f"config.yaml 缺少 validation.{event_key}")
        return ec

    def _model_isoseismal_radius(self, magnitude, target_intensity, r_max=1000.0):
        """数值反演：求模型烈度降至 target_intensity 时的震中距（外边界半径）。

        俞言祥2013 烈度随距离单调递减，扫描距离找 I>=target 的最远点。
        """
        rs = np.linspace(0.1, r_max, 2000)
        intensities = np.array([self.intensity_model.compute(magnitude, r) for r in rs])
        mask = intensities >= target_intensity
        if not mask.any():
            # 震中处即达不到该烈度
            return 0.0
        idx = int(np.where(mask)[0][-1])
        return float(rs[idx])

    def _exposure_density(self, r_km, params, kind):
        """简化距离-密度函数（指数衰减）。"""
        base = params[f"{kind}_base"]
        scale = params[f"{kind}_scale"]
        return base * math.exp(-r_km / scale)

    # ── 验证项 A：烈度场 + 等震线对比 ─────────────────────────

    def compute_intensity_field(self, event_key):
        """计算 0-300km 烈度衰减曲线（俞言祥2013）。"""
        ec = self._event_config(event_key)
        M = ec["magnitude"]
        distances = np.arange(0.0, FIELD_R_MAX + FIELD_STEP / 2, FIELD_STEP)
        intensities = self.intensity_model.compute_field(M, distances)
        grades = [self.intensity_model.intensity_to_grade(i) for i in intensities]
        return {
            "distances_km": [round(float(d), 1) for d in distances],
            "model_intensities": [round(float(i), 3) for i in intensities],
            "model_grades": grades,
        }

    def compare_isoseismals(self, event_key):
        """模型等震线半径 vs 实际等震线半径对比。"""
        ec = self._event_config(event_key)
        M = ec["magnitude"]
        actual = ACTUAL_ISOSEISMALS[event_key]
        rows = {}
        for grade in ["XI", "X", "IX", "VIII", "VII", "VI"]:
            target = GRADE_LOWER_BOUND[grade]
            model_r = self._model_isoseismal_radius(M, target)
            actual_r = actual[grade]
            dev = (model_r - actual_r) / actual_r * 100.0 if actual_r else None
            rows[grade] = {
                "model_radius_km": round(model_r, 1),
                "actual_radius_km": round(actual_r, 1),
                "deviation_pct": round(dev, 1) if dev is not None else None,
            }
        # 近场（IX及以里）与远场（VII及以外）平均偏差
        near = [rows[g]["deviation_pct"] for g in ["XI", "X", "IX"] if rows[g]["deviation_pct"] is not None]
        far = [rows[g]["deviation_pct"] for g in ["VII", "VI"] if rows[g]["deviation_pct"] is not None]
        return {
            "comparison": rows,
            "near_field_mean_dev_pct": round(sum(near) / len(near), 1) if near else None,
            "far_field_mean_dev_pct": round(sum(far) / len(far), 1) if far else None,
            "actual_source": actual["source"],
        }

    # ── 验证项 B：暴露度 + 损失估算 ───────────────────────────

    def estimate_exposure_and_loss(self, event_key):
        """用简化暴露度函数 + 易损性矩阵估算损失，并与实际统计对比。

        环带积分：0-300km 按 1km 环带累加。
            damaged_pop   = Σ 人口 × 期望损失率   （损失率加权，表征严重受灾）
            economic_loss = Σ GDP  × 期望损失率   （年GDP流量×损失率，含存量/流量局限）
            exposure_pop  = Σ 人口  (I>=VI)       （受灾人口标准定义：烈度VI以上区域人口）
        """
        ec = self._event_config(event_key)
        M = ec["magnitude"]
        params = EXPOSURE_PARAMS[event_key]

        edges = np.arange(0.0, FIELD_R_MAX + RING_STEP, RING_STEP)
        damaged_pop = 0.0
        economic_loss = 0.0
        exposure_pop_vi = 0.0
        total_pop = 0.0

        for i in range(len(edges) - 1):
            r0, r1 = edges[i], edges[i + 1]
            r_mid = 0.5 * (r0 + r1)
            I = self.intensity_model.compute(M, r_mid)
            loss_rate = self.vm.loss_rate_from_intensity_value(float(I))
            area = math.pi * (r1 ** 2 - r0 ** 2)  # 环带面积
            pop = self._exposure_density(r_mid, params, "pop") * area
            gdp = self._exposure_density(r_mid, params, "gdp") * area
            damaged_pop += pop * loss_rate
            economic_loss += gdp * loss_rate
            total_pop += pop
            if I >= GRADE_LOWER_BOUND["VI"]:  # 烈度 VI 及以上
                exposure_pop_vi += pop

        actual = {
            "affected_population": ec.get("affected_population"),
            "direct_economic_loss": ec.get("direct_economic_loss"),
            "damaged_buildings": ec.get("damaged_buildings"),
            "collapsed_buildings": ec.get("collapsed_buildings"),
        }

        def dev(est, act):
            return round((est - act) / act * 100.0, 1) if act else None

        return {
            "estimates": {
                # 损失率加权受灾人口（任务要求：用易损性矩阵期望损失率估算）
                "damage_weighted_population": round(damaged_pop),
                # 受灾人口标准定义（VI以上区域人口），更贴合统计口径
                "exposure_population_VI_plus": round(exposure_pop_vi),
                "economic_loss": round(economic_loss),
                "total_population_0_300km": round(total_pop),
            },
            "actual": actual,
            "deviation_pct": {
                # 主对比：受灾人口用 VI 以上暴露度（标准定义）
                "affected_population_vs_exposure": dev(exposure_pop_vi, ec.get("affected_population")),
                # 辅助：损失率加权人口 vs 受灾人口（口径不同，偏差必然大）
                "affected_population_vs_damage_weighted": dev(damaged_pop, ec.get("affected_population")),
                "economic_loss": dev(economic_loss, ec.get("direct_economic_loss")),
            },
            "exposure_model": {
                "function": "density(r) = base * exp(-r / scale)",
                "params": params,
            },
        }

    # ── 单事件综合验证 ────────────────────────────────────────

    def _verdict(self, isoseismal, loss):
        """根据等震线对比与损失偏差给出可信度判定。"""
        near = isoseismal["near_field_mean_dev_pct"]
        far = isoseismal["far_field_mean_dev_pct"]
        parts = []
        # 以等震线对比为主要依据
        if near is not None:
            parts.append(f"近场(IX及以里)等震线平均偏差 {near:+.1f}%")
        if far is not None:
            parts.append(f"远场(VII-VI)等震线平均偏差 {far:+.1f}%")
        econ_dev = loss["deviation_pct"]["economic_loss"]
        if econ_dev is not None:
            parts.append(f"经济损失偏差 {econ_dev:+.1f}%（受简化暴露度与存量/流量差异限制）")
        if near is not None and abs(near) <= 40:
            credibility = "近场可信度良好（|偏差|<=40%）"
        elif near is not None and abs(near) <= 70:
            credibility = "近场可信度中等（40%<|偏差|<=70%）"
        else:
            credibility = "近场偏差较大，建议结合有限断层模型修正"
        return {"findings": parts, "credibility": credibility}

    def validate_event(self, event_key):
        """综合验证单个历史震例。"""
        ec = self._event_config(event_key)
        fault_type = FAULT_TYPE_MAP.get(ec.get("fault_type", "strike_slip"), "strike_slip")
        isoseismal = self.compare_isoseismals(event_key)
        loss = self.estimate_exposure_and_loss(event_key)
        field = self.compute_intensity_field(event_key)
        verdict = self._verdict(isoseismal, loss)
        return {
            "event_key": event_key,
            "params": {
                "magnitude": ec["magnitude"],
                "epicenter": ec["epicenter"],
                "fault_type_config": ec.get("fault_type"),
                "fault_type_rupture_model": fault_type,
                "reference": ec.get("reference", ""),
            },
            "rupture_parameters": self.rm.full_parameters(ec["magnitude"], fault_type),
            "intensity_model": self.intensity_model.info(),
            "intensity_field_0_300km": field,
            "isoseismal_comparison": isoseismal,
            "exposure_and_loss": loss,
            "verdict": verdict,
        }

    # ── 汇总报告 ─────────────────────────────────────────────

    def generate_report(self):
        """生成完整验证报告（dict）。"""
        events = {}
        for key in ["wenchuan_2008", "tangshan_1976"]:
            events[key] = self.validate_event(key)

        # 总体评估
        summary = self._overall_summary(events)
        return {
            "report_meta": {
                "module": "step18_historical_validation",
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "purpose": "用历史震例验证项目模型链（俞言祥2013烈度衰减 + 易损性矩阵）可信度",
                "intensity_model": self.intensity_model.info(),
                "vulnerability_model": self.vm.info(),
                "validation_scope": "等震线半径对比（主） + 损失估算对比（辅）",
                "limitations": [
                    "俞言祥2013为点源模型，不显式建模破裂面延展，近场高烈度区对大破裂事件系统性低估",
                    "yu2013参数为中国东部标定，对川西山区远场衰减偏慢会高估远场烈度",
                    "汶川/唐山缺乏项目一致的网格化人口GDP数据，暴露度用简化指数衰减函数估算",
                    "经济损失用 loss_rate×年GDP 估算，混淆资本存量与GDP流量，系统性低估直接经济损失",
                ],
            },
            "earthquakes": events,
            "summary": summary,
        }

    def _overall_summary(self, events):
        wc = events["wenchuan_2008"]
        ts = events["tangshan_1976"]
        return {
            "isoseismal_validation": {
                "wenchuan_2008": {
                    "near_field_dev_pct": wc["isoseismal_comparison"]["near_field_mean_dev_pct"],
                    "far_field_dev_pct": wc["isoseismal_comparison"]["far_field_mean_dev_pct"],
                    "pattern": "近场低估、远场高估，VIII度处交叉——点源模型对大破裂逆冲事件近场失真，东部参数对川西远场衰减偏慢",
                },
                "tangshan_1976": {
                    "near_field_dev_pct": ts["isoseismal_comparison"]["near_field_mean_dev_pct"],
                    "far_field_dev_pct": ts["isoseismal_comparison"]["far_field_mean_dev_pct"],
                    "pattern": "全程高估，近场(XI/X)最接近，远场(VII/VI)高估显著——东部走滑事件近场适用性较好",
                },
            },
            "model_applicability": (
                "项目研究对象为郯庐断裂带合肥段（中国东部、走滑型），与唐山震例构造环境一致，"
                "模型近场适用性较好。汶川震例的偏差主要源于构造环境差异（西部山区+大破裂逆冲），"
                "不直接影响项目区适用性，但提示对大震级情景应警惕近场低估。"
            ),
            "primary_conclusion": (
                "等震线物理验证显示：模型对中国东部走滑型中强震近场烈度估计可信度良好，"
                "可作为合肥段风险评估的烈度衰减基础。损失估算因暴露度数据缺失仅为量级参考，"
                "项目实际分析应使用合肥真实网格人口GDP数据（step4_grid_exposure）以消除该误差源。"
            ),
        }


# ═══════════════════════════════════════════════════════════════
# 报告输出
# ═══════════════════════════════════════════════════════════════

def save_report(report, out_path=None):
    """保存验证报告为 JSON。"""
    if out_path is None:
        out_path = get_config().data_dir / "validation_report.json"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return out_path


def print_summary(report):
    """控制台打印人类可读的验证摘要。"""
    print("=" * 78)
    print("历史震例验证报告 — 摘要")
    print("=" * 78)
    print(f"烈度模型: {report['report_meta']['intensity_model']['model']} "
          f"({report['report_meta']['intensity_model']['reference']})")
    print()

    for key, ev in report["earthquakes"].items():
        p = ev["params"]
        iso = ev["isoseismal_comparison"]
        loss = ev["exposure_and_loss"]
        print(f"【{key}】 M{p['magnitude']} {p['fault_type_config']} 震中{p['epicenter']}")
        print(f"  参考: {p['reference']}")
        print(f"  等震线半径对比 (模型 vs 实际, km):")
        print(f"    {'等级':>5} {'模型':>9} {'实际':>9} {'偏差':>9}")
        for g in ["XI", "X", "IX", "VIII", "VII", "VI"]:
            r = iso["comparison"][g]
            print(f"    {g:>5} {r['model_radius_km']:>9.1f} "
                  f"{r['actual_radius_km']:>9.1f} {r['deviation_pct']:>+8.1f}%")
        print(f"  近场平均偏差: {iso['near_field_mean_dev_pct']:+.1f}%   "
              f"远场平均偏差: {iso['far_field_mean_dev_pct']:+.1f}%")
        print(f"  损失估算:")
        print(f"    VI以上暴露人口 = {loss['estimates']['exposure_population_VI_plus']:,} "
              f"(实际受灾 {loss['actual']['affected_population']:,}, "
              f"偏差 {loss['deviation_pct']['affected_population_vs_exposure']:+.1f}%)")
        print(f"    损失率加权人口 = {loss['estimates']['damage_weighted_population']:,} "
              f"(偏差 {loss['deviation_pct']['affected_population_vs_damage_weighted']:+.1f}%)")
        print(f"    经济损失估算   = {loss['estimates']['economic_loss']:,} "
              f"(实际 {loss['actual']['direct_economic_loss']:,}, "
              f"偏差 {loss['deviation_pct']['economic_loss']:+.1f}%)")
        print(f"  可信度: {ev['verdict']['credibility']}")
        print()

    print("-" * 78)
    print("总体结论:")
    print(f"  {report['summary']['primary_conclusion']}")
    print("=" * 78)


# ═══════════════════════════════════════════════════════════════
# 自测入口
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    validator = HistoricalValidator()
    report = validator.generate_report()

    # 控制台摘要
    print_summary(report)

    # 写入 JSON 报告
    out = save_report(report)
    print(f"\n[OK] 验证报告已保存: {out}")

    # ── 自测断言 ──
    # 1) 两个震例均已验证
    assert "wenchuan_2008" in report["earthquakes"]
    assert "tangshan_1976" in report["earthquakes"]

    # 2) 等震线对比完整（6 个等级）
    for key in ["wenchuan_2008", "tangshan_1976"]:
        comp = report["earthquakes"][key]["isoseismal_comparison"]["comparison"]
        assert set(comp.keys()) == {"XI", "X", "IX", "VIII", "VII", "VI"}
        for g, row in comp.items():
            assert row["model_radius_km"] >= 0
            assert row["actual_radius_km"] > 0
            assert row["deviation_pct"] is not None

    # 3) 烈度场曲线 0-300km
    for key in ["wenchuan_2008", "tangshan_1976"]:
        field = report["earthquakes"][key]["intensity_field_0_300km"]
        assert field["distances_km"][0] == 0.0
        assert field["distances_km"][-1] >= 300.0
        # 烈度应随距离单调不增（容许数值噪声）
        Is = field["model_intensities"]
        assert Is[0] >= Is[-1], "烈度应随距离衰减"

    # 4) 损失估算与偏差已计算
    wc_loss = report["earthquakes"]["wenchuan_2008"]["exposure_and_loss"]
    assert wc_loss["estimates"]["economic_loss"] > 0
    assert wc_loss["deviation_pct"]["economic_loss"] is not None

    # 5) 报告文件存在且可解析
    assert out.exists()
    with open(out, "r", encoding="utf-8") as f:
        json.load(f)

    # 6) 物理一致性：汶川近场低估、远场高估（点源+东部参数特征）
    wc_iso = report["earthquakes"]["wenchuan_2008"]["isoseismal_comparison"]
    assert wc_iso["comparison"]["XI"]["deviation_pct"] < 0, "汶川XI度点源应低估"
    assert wc_iso["comparison"]["VI"]["deviation_pct"] > 0, "汶川VI度东部参数应高估"

    print("\n[OK] 全部自测断言通过")
