<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import echarts from '../../engine/echartsSetup.js'
import { Target, Activity, ShieldAlert, TrendingUp, GitBranch, Loader2, AlertTriangle, Info, FileText } from 'lucide-vue-next'
import KpiBar from '../shell/KpiBar.vue'

// ==================== DATA SOURCE ====================
const report = ref(null)
const vulnerable = ref(null)
const budget = ref(null)
const loading = ref(true)
const error = ref(null)
const activeMag = ref('6.0') // 动态传染展示震级
const activeSystem = ref('shelter') // 动态传染展示系统

const SYSTEM_COLORS = { medical: '#F87171', transport: '#FBBF24', rescue: '#FB923C', shelter: '#34D399' }
const SYSTEM_NAMES = { medical: '医疗', transport: '交通', rescue: '救援', shelter: '避难' }

async function loadData() {
  try {
    const [r, v, b] = await Promise.all([
      fetch('/data/stress_report.json').then(res => res.json()),
      fetch('/data/vulnerable_exposure.json').then(res => res.json()).catch(() => null),
      fetch('/data/budget_optimization.json').then(res => res.json()).catch(() => null),
    ])
    report.value = r
    vulnerable.value = v
    budget.value = b
    if (r.dynamic_contagion?.highlight_magnitude) {
      activeMag.value = r.dynamic_contagion.highlight_magnitude
    }
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

// ==================== COMPUTED ====================
const rs = computed(() => report.value?.reverse_stress || null)
const magScan = computed(() => rs.value?.magnitude_scan || null)
const epiScan = computed(() => rs.value?.epicenter_scan || null)
const varc = computed(() => report.value?.var_cvar || null)
const contagion = computed(() => report.value?.dynamic_contagion || null)

const critical = computed(() => magScan.value?.critical_magnitudes || {})
const systemCriticalRows = computed(() => [
  { key: 'medical', name: '医疗', mag: critical.value.medical },
  { key: 'rescue', name: '救援', mag: critical.value.rescue },
  { key: 'shelter', name: '避难', mag: critical.value.shelter },
  { key: 'transport', name: '交通', mag: critical.value.transport },
])

const kpiItems = computed(() => {
  const items = []
  const city = critical.value.city
  items.push({ label: '城市崩溃临界', value: city != null ? `M${city.toFixed(1)}` : '—', color: 'red' })
  items.push({ label: '医疗临界', value: critical.value.medical != null ? `M${critical.value.medical.toFixed(1)}` : '—', color: 'yellow' })
  items.push({ label: '避难临界', value: critical.value.shelter != null ? `M${critical.value.shelter.toFixed(1)}` : '—', color: 'green' })
  if (varc.value) {
    items.push({ label: '基准损失', value: `${varc.value.deterministic_loss_yi}亿`, color: 'accent' })
    items.push({ label: 'VaR95', value: `${varc.value.var95_yi}亿`, color: 'red' })
    items.push({ label: 'CVaR95', value: `${varc.value.cvar95_yi}亿`, color: 'purple' })
  }
  const hl = contagion.value?.highlight_magnitude
  if (hl) {
    const r = contagion.value.by_magnitude[hl]
    const drop = Math.max(...Object.values(r.reinforcement_extra_drop))
    items.push({ label: `M${hl}依赖强化下降`, value: `${(drop * 100).toFixed(1)}%`, color: 'orange' })
  }
  return items
})

// ==================== 图表 ====================
const histChartRef = ref(null)
const contagionChartRef = ref(null)
let histChart = null
let contagionChart = null

function renderHistogram() {
  if (!histChartRef.value || !varc.value) return
  histChart = histChart || echarts.init(histChartRef.value)
  const h = varc.value.loss_histogram
  const bins = h.bins
  const mids = bins.slice(0, -1).map((b, i) => (b + bins[i + 1]) / 2)
  const markLines = [
    { xAxis: varc.value.deterministic_loss_yi, name: '基准', color: '#00D4FF' },
    { xAxis: varc.value.var95_yi, name: 'VaR95', color: '#F87171' },
    { xAxis: varc.value.cvar95_yi, name: 'CVaR95', color: '#A78BFA' },
  ]
  histChart.setOption({
    backgroundColor: 'transparent',
    grid: { left: 46, right: 16, top: 28, bottom: 26 },
    tooltip: { trigger: 'axis', backgroundColor: '#142440', borderColor: '#1C2B43', textStyle: { color: '#E6EDF7', fontSize: 11 } },
    title: {
      text: 'M6.0 经济损失分布（蒙特卡洛 500 样本）',
      left: 8, top: 2, textStyle: { color: '#7E91AC', fontSize: 11, fontWeight: 600 },
    },
    xAxis: { type: 'value', name: '亿元', nameTextStyle: { color: '#7E91AC', fontSize: 9 }, axisLabel: { color: '#7E91AC', fontSize: 9 }, splitLine: { lineStyle: { color: 'rgba(28,43,67,0.5)' } } },
    yAxis: { type: 'value', axisLabel: { color: '#7E91AC', fontSize: 9 }, splitLine: { lineStyle: { color: 'rgba(28,43,67,0.5)' } } },
    series: [{
      type: 'bar', data: h.counts, barWidth: '70%',
      itemStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(0,212,255,0.75)' }, { offset: 1, color: 'rgba(0,212,255,0.15)' }] } },
      markLine: {
        symbol: 'none', label: { fontSize: 9, color: '#E6EDF7', formatter: '{b}', position: 'end' },
        lineStyle: { type: 'dashed' },
        data: markLines.map(m => ({ xAxis: m.xAxis, name: m.name, lineStyle: { color: m.color }, label: { color: m.color } })),
      },
    }],
  }, true)
}

function renderContagion() {
  if (!contagionChartRef.value || !contagion.value) return
  contagionChart = contagionChart || echarts.init(contagionChartRef.value)
  const r = contagion.value.by_magnitude[activeMag.value]
  const labels = contagion.value.time_labels
  if (!r) return
  const sys = activeSystem.value
  const fixed = r.fixed_dependency.systems[sys]
  const dyn = r.dynamic_dependency.systems[sys]
  const fct = r.fixed_dependency.collapse_time_by_system[sys]
  const dct = r.dynamic_dependency.collapse_time_by_system[sys]
  const color = SYSTEM_COLORS[sys]
  contagionChart.setOption({
    backgroundColor: 'transparent',
    grid: { left: 40, right: 16, top: 34, bottom: 26 },
    tooltip: { trigger: 'axis', backgroundColor: '#142440', borderColor: '#1C2B43', textStyle: { color: '#E6EDF7', fontSize: 11 } },
    title: {
      text: `M${activeMag.value} · ${SYSTEM_NAMES[sys]}系统功能率演化（固定 vs 时变依赖）`,
      left: 8, top: 2, textStyle: { color: '#7E91AC', fontSize: 11, fontWeight: 600 },
    },
    legend: { right: 8, top: 2, textStyle: { color: '#7E91AC', fontSize: 9 }, data: ['固定依赖', '时变依赖'] },
    xAxis: { type: 'category', data: labels, axisLabel: { color: '#7E91AC', fontSize: 9 }, axisLine: { lineStyle: { color: '#1C2B43' } } },
    yAxis: { type: 'value', min: 0, max: 1.05, name: '功能率', nameTextStyle: { color: '#7E91AC', fontSize: 9 }, axisLabel: { color: '#7E91AC', fontSize: 9 }, splitLine: { lineStyle: { color: 'rgba(28,43,67,0.5)' } } },
    series: [
      { name: '固定依赖', type: 'line', data: fixed, smooth: true, symbolSize: 5, lineStyle: { color: '#7E91AC', width: 2 }, itemStyle: { color: '#7E91AC' } },
      { name: '时变依赖', type: 'line', data: dyn, smooth: true, symbolSize: 5, lineStyle: { color, width: 2.5 }, itemStyle: { color }, areaStyle: { color: 'rgba(251,146,60,0.08)' } },
      ...(fct != null ? [{ type: 'line', markLine: { silent: true, symbol: 'none', label: { show: false }, lineStyle: { color: '#F87171', type: 'dashed' }, data: [{ xAxis: fct <= 0 ? 0 : Math.max(0, labels.indexOf(`T+${fct}h`)) }] } }] : []),
    ],
  }, true)
}

// ==================== 诊断单导出（打印友好 HTML → 另存 PDF） ====================
function exportDiagnosis() {
  if (!report.value) return
  const c = critical.value
  const v = varc.value
  const hl = contagion.value?.highlight_magnitude
  const hlData = hl ? contagion.value.by_magnitude[hl] : null
  const bd = budget.value?.highlights
  const vuln = vulnerable.value?.by_type || []
  const kg = vuln.find(t => t.type === '幼儿园')
  const now = new Date().toLocaleString('zh-CN')

  const row = (k, val, note = '') => `<tr><td class="k">${k}</td><td class="v">${val}</td><td class="n">${note}</td></tr>`
  const html = `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<title>城域底线 · 压测诊断单</title>
<style>
  body { font-family: "Microsoft YaHei", "PingFang SC", sans-serif; color: #1a2332; margin: 32px; }
  h1 { font-size: 22px; border-bottom: 3px solid #00A3C4; padding-bottom: 8px; }
  .meta { color: #667; font-size: 12px; margin: 6px 0 18px; }
  h2 { font-size: 15px; color: #00536B; margin: 22px 0 8px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  td { border: 1px solid #d0d7e0; padding: 6px 10px; }
  td.k { width: 30%; color: #445; background: #f4f8fa; }
  td.v { width: 28%; font-weight: 700; }
  td.n { color: #667; font-size: 12px; }
  .hl { background: #fff7e6; }
  .foot { margin-top: 28px; font-size: 11px; color: #889; border-top: 1px solid #ddd; padding-top: 8px; }
  @media print { body { margin: 12mm; } }
</style></head><body>
<h1>城域底线 · 城市生命线压测诊断单</h1>
<div class="meta">生成时间：${now} ｜ 模型：俞言祥2013 烈度衰减 + 迭代级联 + W&C 破裂参数 ｜ 场景震中：郯庐断裂带合肥段质心</div>

<h2>一、逆压测：城市崩溃底线</h2>
<table>
${row('城市崩溃临界震级', c.city != null ? `M${c.city.toFixed(1)}` : '—', '级联口径连续扫描（M5.0-8.0）')}
${row('医疗系统临界', c.medical != null ? `M${c.medical.toFixed(1)}` : '—', '')}
${row('救援系统临界', c.rescue != null ? `M${c.rescue.toFixed(1)}` : '—', '')}
${row('避难系统临界', c.shelter != null ? `M${c.shelter.toFixed(1)}` : '—', '')}
${row('交通系统', '未崩溃', '全震级')}
</table>

<h2>二、尾部风险（M6.0）</h2>
<table>
${row('基准损失', `${v ? v.deterministic_loss_yi : '—'} 亿元`, 'step8 官方口径（yu2013 烈度场）')}
${row('VaR95（95% 置信上限）', v ? `${v.var95_yi} 亿元` : '—', '蒙特卡洛 500 样本物理参数扰动')}
${row('CVaR95（尾部均值）', v ? `${v.cvar95_yi} 亿元` : '—', '极端参数组合下的期望损失')}
${row('风险准备金目标', v ? `${v.cvar95_yi} 亿元` : '—', '= CVaR95，巨灾保险定价参考')}
</table>

<h2>三、动态传染（灾后依赖强化）</h2>
<table>
${hlData && hl ? row('高亮震级', `M${hl}`, '依赖强化影响最显著') : ''}
${hlData && hl ? row('避难系统（固定依赖）', hlData.fixed_dependency.collapse_time_by_system.shelter != null ? `T+${hlData.fixed_dependency.collapse_time_by_system.shelter}h 失守` : '72h 内未失守', '静态评估') : ''}
${hlData && hl ? row('避难系统（时变依赖）', hlData.dynamic_dependency.collapse_time_by_system.shelter != null ? `T+${hlData.dynamic_dependency.collapse_time_by_system.shelter}h 失守` : '72h 内未失守', '依赖强化后') : ''}
${hlData ? row('依赖强化额外下降', `${(Math.max(...Object.values(hlData.reinforcement_extra_drop)) * 100).toFixed(1)}%`, '避难系统功能率') : ''}
</table>
<div class="hl" style="padding:6px 10px;font-size:12px;margin-top:6px;">
结论：灾后依赖强化使系统比静态评估更早失守——静态依赖评估会<b>高估城市韧性</b>。
</div>

<h2>四、韧性投资（预算优化）</h2>
<table>
${bd ? row('城市崩溃翻转最小预算', `${bd.min_budget_for_city_saved_yi} 亿元`, '优先加固关键路段') : ''}
${bd && bd.min_budget_combination ? row('最优组合', `加固 ${bd.min_budget_combination.roads} 条路段 + ${bd.min_budget_combination.med_points} 医疗点`, '') : ''}
${row('核心发现', '加固路段的收益约为增设医疗点的 10 倍', '医疗崩溃的根源在交通，不在医院本身')}
</table>

<h2>五、脆弱群体暴露（M6.0）</h2>
<table>
${kg ? row('幼儿园', `${(kg.exposure_ratio * 100).toFixed(0)}% 位于高烈度区`, `${kg.high_exposure}/${kg.count} 个`) : ''}
${vuln.filter(t => t.type !== '幼儿园').map(t => row(t.type, `${(t.exposure_ratio * 100).toFixed(0)}% 位于高烈度区`, `${t.high_exposure}/${t.count} 个`)).join('')}
</table>
<div style="padding:6px 10px;font-size:12px;margin-top:6px;background:#f4f8fa;">
结论：灾难中最脆弱的群体暴露最高——这是城市"底线债务"最直接的证据。
</div>

<div class="foot">
城域底线 · 大数据压测诊断系统（中国大学生计算机设计大赛参赛作品）<br>
口径说明：损失率采用 step8 分档（VII 5% / VIII 20% / X 50%）；可达性为最保守判定；
完整口径与已知边界见 docs/数据口径说明.md。
</div>
</body></html>`

  const w = window.open('', '_blank', 'width=900,height=700')
  if (!w) { copied.value = true; setTimeout(() => copied.value = false, 1500); return }
  w.document.write(html)
  w.document.close()
  setTimeout(() => { w.focus(); w.print() }, 300)
}
const copied = ref(false)

// ==================== 生命周期 ====================
let resizeHandler = null

onMounted(async () => {
  await loadData()
  await nextTick()
  renderHistogram()
  renderContagion()
  resizeHandler = () => { histChart?.resize(); contagionChart?.resize() }
  window.addEventListener('resize', resizeHandler)
})

onBeforeUnmount(() => {
  if (resizeHandler) window.removeEventListener('resize', resizeHandler)
  histChart?.dispose()
  contagionChart?.dispose()
})

watch(activeMag, () => nextTick(renderContagion))
watch(activeSystem, () => nextTick(renderContagion))
watch(() => report.value, () => { nextTick(() => { renderHistogram(); renderContagion() }) })
</script>

<template>
  <div class="mode-root">
    <div v-if="loading" class="loading-overlay">
      <Loader2 :size="24" class="spin" style="color:var(--state-info);" />
      <span style="margin-left:8px;font-size:12px;color:var(--av-muted-foreground);">加载压测数据...</span>
    </div>
    <div v-else-if="error" class="loading-overlay">
      <AlertTriangle :size="24" style="color:var(--state-error);" />
      <span style="margin-left:8px;font-size:12px;color:var(--state-error);">加载失败: {{ error }}</span>
    </div>
    <template v-else>
      <KpiBar :items="kpiItems" />

      <!-- 导出诊断单 -->
      <div class="export-bar">
        <button class="export-btn" @click="exportDiagnosis">
          <FileText :size="11" style="vertical-align:-1px;" /> {{ copied ? '已生成 ✓' : '导出诊断单(PDF)' }}
        </button>
        <span class="export-hint">生成打印友好诊断单（浏览器另存为 PDF）</span>
      </div>

      <!-- === 左栏：逆压测 === -->
      <div class="col-panel">
        <div class="panel-item accent">
          <div class="panel-label"><Target :size="11" style="vertical-align:-1px;" /> 城市崩溃临界震级</div>
          <div class="big-number" :class="critical.city != null ? 'red' : ''">
            {{ critical.city != null ? 'M' + critical.city.toFixed(1) : '—' }}
          </div>
          <div class="panel-desc">反向搜索：在什么震级下城市生命线开始系统性失守</div>
          <div class="critical-grid">
            <div v-for="row in systemCriticalRows" :key="row.key" class="critical-cell">
              <div class="critical-name">{{ row.name }}</div>
              <div class="critical-mag" :style="{ color: SYSTEM_COLORS[row.key] }">
                {{ row.mag != null ? 'M' + row.mag.toFixed(1) : '未崩' }}
              </div>
            </div>
          </div>
        </div>

        <div class="panel-item">
          <div class="panel-label"><Activity :size="11" style="vertical-align:-1px;" /> 最不利破裂位置</div>
          <div v-if="epiScan" class="epi-row">
            <div class="data-row"><span class="data-row-key">基准震中（质心）</span><span class="data-row-val">临界 M{{ epiScan.baseline_epicenter.critical_mag != null ? epiScan.baseline_epicenter.critical_mag.toFixed(1) : '—' }}</span></div>
            <div class="data-row"><span class="data-row-key">最不利位置</span><span class="data-row-val red">{{ epiScan.most_vulnerable.critical_mag != null ? 'M' + epiScan.most_vulnerable.critical_mag.toFixed(1) : '—' }}</span></div>
            <div class="data-row"><span class="data-row-key">坐标</span><span class="data-row-val">{{ epiScan.most_vulnerable.lon }}, {{ epiScan.most_vulnerable.lat }}</span></div>
            <div class="data-row"><span class="data-row-key">烈度差 dI</span><span class="data-row-val">{{ epiScan.most_vulnerable.dI_bar }}</span></div>
            <div class="data-row"><span class="data-row-key">敏感性范围</span><span class="data-row-val">{{ epiScan.most_vulnerable.dI_bar - epiScan.safest.dI_bar }}</span></div>
          </div>
          <div class="panel-desc">断裂带沿线 ±30km 网格扫描（dI=人口加权平均烈度差，正=更危险）</div>
        </div>

        <div class="panel-item" v-if="magScan?.caliber_note">
          <div class="panel-label"><Info :size="11" style="vertical-align:-1px;" /> 口径说明</div>
          <div class="attribution-intro">{{ magScan.caliber_note }}</div>
        </div>
      </div>

      <!-- === 中栏：VaR/CVaR === -->
      <div class="col-center">
        <div class="map-container">
          <div class="map-toolbar">
            <div class="map-info"><TrendingUp :size="12" style="vertical-align:middle;" /> 尾部风险 · VaR / CVaR</div>
          </div>
          <div ref="histChartRef" style="position:absolute;top:0;left:0;width:100%;height:100%;"></div>
        </div>
        <div class="metric-strip" v-if="varc">
          <div class="metric-cell"><div class="metric-label">确定性基准</div><div class="metric-value accent">{{ varc.deterministic_loss_yi }}亿</div></div>
          <div class="metric-cell"><div class="metric-label">期望损失</div><div class="metric-value">{{ varc.mean_loss_yi }}亿</div></div>
          <div class="metric-cell"><div class="metric-label">VaR95 上限</div><div class="metric-value red">{{ varc.var95_yi }}亿</div></div>
          <div class="metric-cell"><div class="metric-label">CVaR95 尾部</div><div class="metric-value purple">{{ varc.cvar95_yi }}亿</div></div>
        </div>
        <div class="panel-item green">
          <div class="panel-label"><ShieldAlert :size="11" style="vertical-align:-1px;" /> 金融语言解读</div>
          <div class="attribution-intro">
            基准情景损失约 {{ varc?.deterministic_loss_yi }} 亿元（占全市 GDP 约
            {{ (varc?.deterministic_loss_yi / 10109 * 100).toFixed(1) }}%）；考虑烈度衰减与易损性
            不确定性后，<b>95% 置信下损失不超过 {{ varc?.var95_yi }} 亿元</b>，尾部均值
            {{ varc?.cvar95_yi }} 亿元——这是为巨灾保险定价与风险准备金留出的安全边际。
          </div>
        </div>
      </div>

      <!-- === 右栏：动态传染 === -->
      <div class="col-panel">
        <div class="panel-item">
          <div class="panel-label"><GitBranch :size="11" style="vertical-align:-1px;" /> 动态传染 · 时变依赖</div>
          <div class="seg-control" v-if="contagion">
            <button v-for="m in contagion.magnitudes" :key="m"
                    class="seg-btn" :class="{ active: activeMag === String(m) }"
                    @click="activeMag = String(m)">M{{ m.toFixed(1) }}</button>
          </div>
          <div class="seg-control" style="margin-top:4px;">
            <button v-for="(nm, k) in SYSTEM_NAMES" :key="k"
                    class="seg-btn" :class="{ active: activeSystem === k }"
                    @click="activeSystem = k">{{ nm }}</button>
          </div>
          <div ref="contagionChartRef" style="width:100%;height:200px;"></div>
          <div v-if="contagion?.by_magnitude[activeMag]" class="finding-item">
            <span class="finding-dot" style="background:var(--state-warning);"></span>
            <span>
              M{{ activeMag }} · {{ SYSTEM_NAMES[activeSystem] }}：固定依赖
              {{ contagion.by_magnitude[activeMag].fixed_dependency.collapse_time_by_system[activeSystem] != null ? 'T+' + contagion.by_magnitude[activeMag].fixed_dependency.collapse_time_by_system[activeSystem] + 'h 失守' : '72h 内未失守' }}
              → 时变依赖
              {{ contagion.by_magnitude[activeMag].dynamic_dependency.collapse_time_by_system[activeSystem] != null ? 'T+' + contagion.by_magnitude[activeMag].dynamic_dependency.collapse_time_by_system[activeSystem] + 'h 失守' : '72h 内未失守' }}
              （依赖强化额外下降
              {{ (contagion.by_magnitude[activeMag].reinforcement_extra_drop[activeSystem] * 100).toFixed(1) }}%）
            </span>
          </div>
        </div>
        <div class="panel-item accent">
          <div class="panel-label">核心发现</div>
          <div class="attribution-intro">
            灾后依赖强化（路断越久医疗越缺物资、危险源失控风险上升）使系统比静态评估
            更早失守。M6.0 下避难系统从"72h 勉强存活"变为"T+72h 失守"——
            <b>静态依赖评估会高估城市韧性</b>，动态传染是更真实的压力测试。
          </div>
        </div>

        <div class="panel-item" v-if="vulnerable?.by_type?.length">
          <div class="panel-label">脆弱群体设施暴露 · M6.0</div>
          <div class="vuln-list">
            <div v-for="t in vulnerable.by_type" :key="t.type" class="vuln-row">
              <div class="vuln-head">
                <span class="vuln-name">{{ t.type }}</span>
                <span class="vuln-meta">{{ t.high_exposure }}/{{ t.count }} 个 · {{ (t.exposure_ratio * 100).toFixed(0) }}%</span>
              </div>
              <div class="probe-track">
                <div class="probe-fill" :style="{ width: (t.exposure_ratio * 100) + '%', background: t.exposure_ratio > 0.6 ? 'var(--state-error)' : (t.exposure_ratio > 0.4 ? 'var(--state-warning)' : 'var(--state-success)') }"></div>
              </div>
            </div>
          </div>
          <div class="panel-desc">
            幼儿园 {{ (vulnerable.by_type.find(t => t.type === '幼儿园')?.exposure_ratio * 100 || 0).toFixed(0) }}% 位于高烈度区
            ——灾难中最脆弱的群体暴露最高，这是"底线债务"最直接的证据。
          </div>
        </div>

        <!-- 预算优化：韧性投资资本配置 -->
        <div class="panel-item" v-if="budget?.highlights">
          <div class="panel-label">韧性投资 · 预算优化</div>
          <div class="budget-hero">
            <div class="budget-hero-num">{{ budget.highlights.min_budget_for_city_saved_yi }}亿</div>
            <div class="budget-hero-label">即可让城市崩溃翻转</div>
          </div>
          <div class="budget-bar">
            <div v-for="c in budget.budget_curve.filter((_, i) => i % 4 === 0)" :key="c.budget_yi"
                 class="budget-bar-col" :class="{ saved: c.city_saved }"
                 :style="{ height: (c.medical_after * 160) + 'px' }"
                 :title="`预算${c.budget_yi}亿 → 医疗功能率${(c.medical_after * 100).toFixed(1)}%`">
            </div>
          </div>
          <div class="budget-legend">
            <span class="budget-legend-item"><span class="dot saved"></span>城市可维持</span>
            <span class="budget-legend-item"><span class="dot"></span>仍崩溃</span>
          </div>
          <div class="panel-desc" style="margin-top:4px;">
            {{ budget.interpretation }}
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.big-number { font-size: 30px; font-weight: 800; font-family: var(--av-font-mono); line-height: 1.1; }
.big-number.red { color: var(--state-error); }
.panel-desc { font-size: 9.5px; color: var(--av-muted-foreground); line-height: 1.5; margin-top: 2px; }
.critical-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; margin-top: 8px; }
.critical-cell { background: rgba(15,26,43,0.6); border: 1px solid var(--av-border); border-radius: 4px; padding: 5px 7px; }
.critical-name { font-size: 9px; color: var(--av-muted-foreground); }
.critical-mag { font-size: 15px; font-weight: 700; font-family: var(--av-font-mono); }
.epi-row { display: flex; flex-direction: column; gap: 2px; margin-top: 4px; }
.data-row { display: flex; justify-content: space-between; align-items: center; font-size: 10px; padding: 2px 0; border-bottom: 1px dashed rgba(28,43,67,0.5); }
.data-row-key { color: var(--av-muted-foreground); }
.data-row-val { font-weight: 600; font-family: var(--av-font-mono); }
.data-row-val.red { color: var(--state-error); }
.metric-strip { display: flex; gap: 6px; margin: 6px 0; }
.metric-cell { flex: 1; background: var(--av-muted); border: 1px solid var(--av-border); border-radius: 4px; padding: 5px 6px; text-align: center; }
.metric-label { font-size: 9px; color: var(--av-muted-foreground); }
.metric-value { font-size: 14px; font-weight: 700; font-family: var(--av-font-mono); }
.metric-value.accent { color: var(--state-info); }
.metric-value.red { color: var(--state-error); }
.metric-value.purple { color: var(--state-purple); }
.seg-control { display: flex; gap: 4px; flex-wrap: wrap; }
.seg-btn { flex: 1; min-width: 34px; padding: 3px 6px; font-size: 9.5px; color: var(--av-muted-foreground); background: rgba(15,26,43,0.6); border: 1px solid var(--av-border); border-radius: 3px; cursor: pointer; }
.seg-btn.active { color: var(--av-primary); border-color: var(--primary-border); background: var(--primary-dim); }
.attribution-intro { font-size: 9.5px; line-height: 1.6; color: var(--av-foreground); }
.attribution-intro b { color: var(--av-primary); }
.vuln-list { display: flex; flex-direction: column; gap: 5px; margin: 6px 0; }
.vuln-row { display: flex; flex-direction: column; gap: 2px; }
.vuln-head { display: flex; justify-content: space-between; font-size: 9.5px; }
.vuln-name { font-weight: 700; }
.vuln-meta { font-family: var(--av-font-mono); color: var(--av-muted-foreground); }
.budget-hero { text-align: center; padding: 6px 0 2px; }
.budget-hero-num { font-size: 26px; font-weight: 800; font-family: var(--av-font-mono); color: var(--state-success); }
.budget-hero-label { font-size: 9.5px; color: var(--av-muted-foreground); }
.budget-bar { display: flex; align-items: flex-end; gap: 2px; height: 170px; padding: 6px 2px 0; border-bottom: 1px solid var(--av-border); }
.budget-bar-col { flex: 1; min-width: 8px; background: rgba(248,113,113,0.55); border-radius: 2px 2px 0 0; }
.budget-bar-col.saved { background: linear-gradient(180deg, rgba(52,211,153,0.9), rgba(52,211,153,0.35)); }
.budget-legend { display: flex; gap: 10px; margin-top: 4px; font-size: 8.5px; color: var(--av-muted-foreground); }
.budget-legend-item { display: flex; align-items: center; gap: 3px; }
.dot { width: 6px; height: 6px; border-radius: 2px; background: rgba(248,113,113,0.7); display: inline-block; }
.dot.saved { background: var(--state-success); }
.export-bar { display: flex; align-items: center; gap: 8px; margin: 2px 0 6px; }
.export-btn { display: inline-flex; align-items: center; gap: 4px; padding: 3px 10px; font-size: 10px; font-weight: 600; color: var(--av-primary); background: var(--primary-dim); border: 1px solid var(--primary-border); border-radius: 3px; cursor: pointer; }
.export-btn:hover { background: rgba(0,212,255,0.2); }
.export-hint { font-size: 9px; color: var(--av-muted-foreground); }
</style>
