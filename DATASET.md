# 数据集说明 — DATASET

## 数据来源

| 数据 | 来源 | 说明 |
|------|------|------|
| 行政边界 | DataV.GeoAtlas (阿里云) | 合肥市9区县 GeoJSON, EPSG:4490 |
| 郯庐断裂带 | CAFD2023 中国活动断层数据库 | 合肥段几何, CN-faults.gmt |
| 医疗设施 | 高德地图 POI API | 426家医院/卫生中心 |
| 道路网络 | OpenStreetMap (OSM) | 58K路段, networkx图模型 |
| 人口/GDP | 统计年鉴 + 面积加权降尺度 | 9区县人口GDP分布 |
| 夜间灯光 | NASA NPP-VIIRS DNB | 500m分辨率人口降尺度（回退面积加权） |
| 历史震例 | 中国地震局官方报告 | 汶川2008/唐山1976等震线+损失数据 |

## 坐标系

| 用途 | 坐标系 | 说明 |
|------|--------|------|
| 数据存储 | EPSG:4490 | CGCS2000 地理坐标 |
| 空间计算 | EPSG:4527 | CGCS2000 3度带39（投影，单位米） |
| 前端渲染 | EPSG:4326 | WGS84（Leaflet兼容） |

## 数据文件清单

### 前端数据（dashboard/public/data/）

| 文件 | 大小 | 说明 |
|------|------|------|
| dashboard_M{5.0~7.5}.json | ~1.6MB×6 | 各震级完整分析数据（KPI/地图/图表/级联/敏感性/时间演化） |
| sensitivity_report.json | 29KB | 全局敏感性分析报告（蒙特卡洛+龙卷风+相关分析） |
| time_stepping.json | 50KB | 全震级时间步进演化数据 |
| validation_report.json | 16KB | 历史震例验证报告（汶川+唐山） |
| multi_source_comparison.json | 302KB | 4震源情景对比数据 |

### 地理数据（dashboard/public/data/geo/）

| 文件 | 说明 |
|------|------|
| hefei_districts_4490.geojson | 合肥行政区划 |
| tanlu_fault_hefei_4490.geojson | 郯庐断裂带 |
| hefei_roads_lite.geojson | 精简路网 |
| road_blocked_M{5.0~7.5}_lite.geojson | 各震级阻断路网 |
| facilities_hazards_real.geojson | 危险源设施 |
| facilities_rescue_real.geojson | 救援设施 |
| facilities_shelters_real.geojson | 避难设施 |
| hefei_hospital.geojson | 医疗设施 |

### 算法中间数据（数据文件/）

| 文件 | 说明 |
|------|------|
| grid_intensity_M{5.0~7.5}.csv | 网格烈度场 |
| exposure_summary_M{5.0~7.5}.csv | 暴露度汇总 |
| loss_estimate_M{5.0~7.5}.csv | 损失估算 |
| accessibility_M{5.0~7.5}.csv | 可达性分析 |
| accessibility_facilities_M{5.0~7.5}.csv | 设施可达性 |
| resilience_index_M{5.0~7.5}.csv | 韧性指数 |
| cascade_threshold.csv | 级联崩溃阈值 |
| collapse_threshold.csv | 崩溃阈值表 |
| prevention_strategy.csv | 防御策略 |
| hefei_road_graph.graphml | 路网图模型（networkx） |
| grid_population_gdp.csv | 网格人口GDP |
| key_roads.csv | 关键路段 |
| graph_nodes.csv | 图节点 |

## dashboard_M{X}.json 数据段结构

```
{
  "meta": { "magnitude", "epicenter", "generate_time" },
  "kpi": { "total_population", "exposed_population", "affected_population",
           "total_gdp_yi", "economic_loss_yi", "total_hospitals",
           "accessible_hospitals", "inaccessible_hospitals",
           "road_block_rate", "city_collapse" },
  "map_layers": { "intensity_grid": [...], ... },
  "charts": { "district_loss", "spatial_mismatch", "magnitude_curve", "resilience" },
  "prevention": { "strategies": [{ "strategy", "description", "medical_ratio_before/after",
                                    "rescue_ratio_before/after", "threshold_shift",
                                    "city_collapse_after", "key_roads_repaired",
                                    "temp_medical_points_added" }] },
  "cascade": { "systems": { "medical/transport/rescue/shelter": {
                "base_ratio", "cascade_ratio", "cascade_drop", "collapsed", "status" },
              "dependency_matrix", "cascade_timeline", "city_cascade_collapse",
              "cascade_depth", "propagation_paths_count" },
  "sensitivity": { "magnitude", "n_samples", "collapse_probability",
                   "tornado": [{ "param", "label", "base", "low", "high",
                                 "base_resilience", "low_resilience", "high_resilience" }],
                   "parameter_importance": [{ "param", "label", "rho", "significant" }],
                   "threshold_distribution": { "mean", "std", "median", "p5/p25/p75/p95" },
                   "system_confidence_intervals": [{ "system", "mean", "std", "p5", "p95" }] },
  "time_evolution": { "first_collapse_time", "steps": [{
                "time", "label", "desc", "cascade_factor",
                "systems": { "medical/transport/rescue/shelter": {
                  "ratio", "drop", "collapsed", "status", "threshold" } },
                "city_collapse", "collapsed_count" }] }
}
```

## 震级情景

| 参数 | 值 |
|------|-----|
| 震级范围 | M5.0, M5.5, M6.0, M6.5, M7.0, M7.5 |
| 震中 | 117.28°E, 31.82°N（郯庐断裂带合肥段质心） |
| 断裂带 | 郯庐断裂带合肥段 |
| 断层类型 | 走滑断层（strike-slip） |
| 破裂模型 | Wells & Coppersmith 1994 |
