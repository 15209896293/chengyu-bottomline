# 城域底线 — 合肥市地震灾害链级联崩溃分析系统

> 中国大学生计算机设计大赛参赛作品
>
> 以郯庐断裂带合肥段为研究对象，构建"烈度衰减 → 易损性评估 → 级联传播 → 韧性优化"全链路城市地震底线分析系统。

## 核心创新

| 创新点 | 方法 | 学术依据 |
|--------|------|----------|
| 烈度衰减模型 | 俞言祥2013中国东部分区衰减关系 | GB18306-2015 国家地震动参数区划图 |
| 易损性矩阵 | 烈度-破坏概率分布 | DB53/T 1475 区域地震灾害损失预评估规范 |
| 破裂带参数 | Wells & Coppersmith 1994 经验关系 | BSSA 84(4):974-1002 |
| 级联传播模型 | 迭代传播至收敛（Leontief框架） | Haimes & Jiang 2001, J. Infrastructure Systems |
| 敏感性分析 | 蒙特卡洛500次 + OAT + Spearman秩相关 | Saltelli et al. 2008, Global Sensitivity Analysis |
| 历史验证 | 汶川2008/唐山1976等震线对比 | 中国地震局官方烈度分布图 |

## 技术栈

**算法层（Python）**: numpy, pandas, geopandas, networkx, osmnx, shapely
**前端层（Vue 3）**: Vue 3.5, ECharts 5.6, Leaflet 1.9, TailwindCSS 4, Vite 6
**设计风格**: 暗色科技风（#0A1320 + #00D4FF）

## 目录结构

```
城域底线/
├── 算法脚本/                    # Python 算法管线
│   ├── config.yaml              # 全局参数配置中心
│   ├── config_loader.py         # 配置加载器
│   ├── intensity_model.py       # 烈度衰减模型（俞言祥2013）
│   ├── vulnerability_matrix.py  # 易损性矩阵（DB53/T 1475）
│   ├── rupture_model.py         # 破裂带参数（Wells & Coppersmith 1994）
│   ├── cascade_model.py         # 迭代传播级联模型
│   ├── step1-step15             # 主分析管线
│   ├── step16_time_stepping.py  # 时间步进演化（T+0→T+72h）
│   ├── step17_sensitivity.py    # 蒙特卡洛敏感性分析
│   ├── step18_historical_validation.py  # 历史震例验证
│   └── step19_multi_source.py   # 多震源情景对比
├── dashboard/                   # Vue 3 前端
│   ├── src/
│   │   ├── components/modes/    # 6个分析模式
│   │   │   ├── PatternMode.vue      # 1.格局：网络拓扑
│   │   │   ├── ThresholdMode.vue    # 2.临界：崩溃阈值
│   │   │   ├── CascadeMode.vue      # 3.级联：传播路径+时间推演
│   │   │   ├── ResilienceMode.vue   # 4.韧性：策略优化
│   │   │   ├── SandboxMode.vue      # 5.沙盘：参数敏感性
│   │   │   └── ValidationMode.vue   # 6.验证：历史震例+多震源
│   │   ├── composables/         # Vue 组合式函数
│   │   └── assets/styles/       # 设计令牌 + 全局样式
│   └── public/data/             # 前端数据文件
├── 数据文件/                    # 算法工作区（输入 + 输出中间产物）
│   └── archive_202607/         # 归档：可再生/备份中间产物（simulated 备份、调试 HTML）
├── uii设计/                    # 历史 UI 设计稿（HTML 原型）
│   └── archive_旧4模式模板/    # 归档：旧 4 模式交互模板（格局/临界/级联/韧性）
└── docs/                        # 项目文档（计划书/研究报告/开发日志等）
```

## 快速开始

### 环境准备

```bash
# 1. 创建 conda 环境
conda create -n zhenmai python=3.10
conda activate zhenmai

# 2. 安装 GDAL/PROJ
conda install -c conda-forge gdal proj-data

# 3. 安装 Python 依赖
pip install -r requirements.txt
```

### 运行算法管线

```bash
cd 算法脚本

# 按顺序执行（step1 需先完成数据采集）
python step2_fault_buffer.py         # 断裂带缓冲区
python step3_hospital_poi.py         # 医疗设施POI
python step4_grid_exposure.py        # 网格暴露度
python step5_road_blocking.py        # 道路阻断
python step6_generate_facilities.py  # 设施生成
python step7_cascade_analysis.py     # 级联分析
python step8_loss_recalculation.py   # 损失重算
python step9_unified_accessibility.py # 可达性分析
python step10_collapse_threshold.py  # 崩溃阈值
python step12_export_json.py         # 导出JSON
python step13_resilience_index.py    # 韧性指数
python step14_prevention_strategy.py # 防御策略
python step15_cascade_propagation.py # 级联传播

# 高级分析（基于核心模型）
python step16_time_stepping.py       # 时间步进演化
python step17_sensitivity.py         # 敏感性分析
python step18_historical_validation.py  # 历史验证
python step19_multi_source.py        # 多震源对比
python step20_reverse_stress.py      # 逆压测 + VaR/CVaR + 动态传染
python step21_fault_risk_profile.py  # 断裂带风险剖面
python step22_vulnerable_facilities.py  # 脆弱群体设施暴露（需高德配额）
python step23_budget_optimization.py # 预算约束韧性投资优化
python stressor_model.py             # 压力源抽象层自检
```

### 启动前端

```bash
cd dashboard
npm install
npm run dev      # 开发模式
npm run build    # 生产构建
```

### 双形态交付

**① 本地离线演示（断网可用）**

```bash
# Windows: 双击 start-offline.bat（自动启动 http://localhost:8080）
# macOS/Linux: bash start-offline.sh
```

已离线化：无 Google Fonts 外链、系统字体栈、高德瓦片断网自动降级为深色底+提示条、
数据全量随包（dist/data 26MB）。压缩包 `城域底线_离线演示包.zip` 可直接分发。

**② Cloudflare Pages 线上部署**

```bash
# 1. 仓库推送 GitHub main 分支后，CI（.github/workflows/deploy.yml）自动构建
# 2. 仓库 Secrets 配置：
#    CLOUDFLARE_API_TOKEN    # Cloudflare 平台 API Token（Pages 权限）
#    CLOUDFLARE_ACCOUNT_ID   # Cloudflare 账户 ID
# 3. Cloudflare Pages 创建项目 chengyu-bottomline，构建命令 npm run build，
#    输出目录 dashboard/dist（CI 使用 wrangler pages deploy 直推）
```

## 分析模式说明

| 模式 | 名称 | 功能 |
|------|------|------|
| 1 | 格局 PATTERN | 城市基础设施网络拓扑 + 空间格局分析 |
| 2 | 临界 COLLAPSE THRESHOLD | 4系统崩溃阈值 + 跨震级临界点识别 + 实时推演探针 |
| 3 | 级联 CASCADE | 迭代传播路径 + T+0→T+72h时间步进推演 |
| 4 | 韧性 RESILIENCE | 3策略对比 + ROI分析 + 阈值推移效果 |
| 5 | 沙盘 SENSITIVITY | 8参数交互滑块 + 蒙特卡洛 + 龙卷风图 |
| 6 | 验证 VALIDATION | 汶川/唐山等震线验证 + 4震源情景对比 + 误差归因 |
| 7 | 压测 REVERSE STRESS | 逆压测（临界震级/破裂位置扫描）+ VaR/CVaR + 动态传染 + 预算优化 + 脆弱群体暴露 |

## 震级情景

6个震级情景：M5.0, M5.5, M6.0, M6.5, M7.0, M7.5

震中：郯庐断裂带合肥段几何质心（117.28°E, 31.82°N）

## 关键参数

所有参数集中在 `config.yaml` 中管理，包括：
- 烈度衰减系数（俞言祥2013）
- 易损性矩阵（DB53/T 1475）
- 跨系统依赖权重矩阵
- 崩溃阈值
- 时间步进参数
- 蒙特卡洛采样参数

## 参考文献

1. 俞言祥. 中国分区地震动衰减关系的确定. 震灾防御技术, 2013.
2. Wells, D.L., Coppersmith, K.J. New empirical relationships among magnitude, rupture length, rupture width, rupture area, and surface displacement. BSSA, 84(4):974-1002, 1994.
3. Haimes, Y.Y., Jiang, P. Leontief-based model of risk in complex interconnected infrastructures. J. Infrastructure Systems, 7(1):1-12, 2001.
4. DB53/T 1475. 区域地震灾害损失预评估技术规范.
5. GB 18306-2015. 中国地震动参数区划图.
6. Saltelli, A. et al. Global Sensitivity Analysis: The Primer. Wiley, 2008.
