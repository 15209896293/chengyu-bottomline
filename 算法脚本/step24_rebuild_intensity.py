"""
step24_rebuild_intensity.py — 烈度场口径规范化（yu2013）

修复：旧 grid_intensity_M*.csv 使用简化 ATTEN 公式（0.5+1.5M-ln(R+5)），
与项目方法论声明"俞言祥2013 烈度衰减"矛盾。统一改用 IntensityModel(yu2013)
重算全部 6 个震级的网格烈度场，保证：
  - 与历史验证（step18）公式一致
  - 与前端实时引擎（realTimeEngine.calcIntensity）一致
  - 与 VaR 扰动（step20）一致

输出：数据文件/grid_intensity_M{5.0..7.5}.csv（覆盖，可复现）
"""
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from intensity_model import IntensityModel
from config_loader import get_config

DATA_DIR = Path(__file__).resolve().parent.parent / "数据文件"
MAGNITUDES = [5.0, 5.5, 6.0, 6.5, 7.0, 7.5]


def loss_rate_step8(i):
    """step8 官方口径损失率分档（与 loss_estimate 一致）。"""
    if i < 5:
        return 0.0
    elif i < 7:
        return 0.05
    elif i < 8:
        return 0.20
    else:
        return 0.50


def main():
    print("=" * 60)
    print("烈度场口径规范化（yu2013 替换简化 ATTEN）")
    print("=" * 60)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    imodel = IntensityModel()
    assert imodel.model_name == "yu2013", f"模型应为 yu2013，实际 {imodel.model_name}"

    pop = pd.read_csv(DATA_DIR / "grid_population_gdp.csv", encoding="utf-8-sig")
    dist = pop["dist_to_epi_km"].astype(float).values
    hosp = pop["hospital_count"].astype(float).values

    # 对比：旧简化公式 vs yu2013（M5.0 @ 100km 示例）
    old_100 = 0.5 + 1.5 * 5.0 - np.log(100 + 5.0)
    new_100 = imodel.compute(5.0, 100.0)
    print(f"\n口径对比（M5.0 @100km）: 旧简化={old_100:.3f} → yu2013={new_100:.3f}")

    for mag in MAGNITUDES:
        intensity = imodel.compute_field(mag, dist)
        loss_rate = np.array([loss_rate_step8(x) for x in intensity])
        grid_loss = hosp * loss_rate
        df = pd.DataFrame({
            "cell_id": pop["cell_id"].values,
            "intensity": np.round(intensity, 6),
            "loss_rate": loss_rate,
            "grid_loss": np.round(grid_loss, 4),
        })
        out = DATA_DIR / f"grid_intensity_M{mag:.1f}.csv"
        df.to_csv(out, index=False, encoding="utf-8-sig")
        print(f"  M{mag:.1f}: 烈度 {intensity.min():.2f}-{intensity.max():.2f} "
              f"(均值 {intensity.mean():.2f}) | 已保存 {out.name}")

    # 自检：与 loss_estimate 口径核对（gdp×loss_rate ≈ 官方基准）
    gdp = pop["gdp_yi"].astype(float).values
    for mag in [5.0, 6.0, 7.0]:
        df = pd.read_csv(DATA_DIR / f"grid_intensity_M{mag:.1f}.csv", encoding="utf-8-sig")
        loss = float(np.sum(gdp * df["loss_rate"].values))
        print(f"  自检 M{mag:.1f}: gdp×loss_rate = {loss:.2f} 亿元")

    print("\n[OK] 烈度场重建完成（6 震级，yu2013 口径）")


if __name__ == "__main__":
    main()
