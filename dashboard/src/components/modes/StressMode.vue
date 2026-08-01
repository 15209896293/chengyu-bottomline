<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import * as echarts from 'echarts'
import { Target, Activity, ShieldAlert, TrendingUp, GitBranch, Loader2, AlertTriangle, Info } from 'lucide-vue-next'
import KpiBar from '../shell/KpiBar.vue'

// ==================== DATA SOURCE ====================
const report = ref(null)
const loading = ref(true)
const error = ref(null)
const activeMag = ref('6.0') // 动态传染展示震级
const activeSystem = ref('shelter') // 动态传染展示系统

const SYSTEM_COLORS = { medical: '#F87171', transport: '#FBBF24', rescue: '#FB923C', shelter: '#34D399' }
const SYSTEM_NAMES = { medical: '医疗', transport: '交通', rescue: '救援', shelter: '避难' }

async function loadData() {
  try {
    const r = await fetch('/data/stress_report.json').then(res => res.json())
    report.value = r
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
            <div class="data-row"><span class="data-row-key">基准震中</span><span class="data-row-val">临界 M{{ epiScan.baseline_epicenter.critical_mag != null ? epiScan.baseline_epicenter.critical_mag.toFixed(1) : '—' }}</span></div>
            <div class="data-row"><span class="data-row-key">最不利位置</span><span class="data-row-val red">{{ epiScan.most_vulnerable.critical_mag != null ? 'M' + epiScan.most_vulnerable.critical_mag.toFixed(1) : '—' }}</span></div>
            <div class="data-row"><span class="data-row-key">坐标</span><span class="data-row-val">{{ epiScan.most_vulnerable.lon }}, {{ epiScan.most_vulnerable.lat }}</span></div>
            <div class="data-row"><span class="data-row-key">烈度偏移</span><span class="data-row-val">{{ epiScan.most_vulnerable.dI_bar }}</span></div>
          </div>
          <div class="panel-desc">断裂带沿线 ±30km 网格扫描：破裂位置偏移会改变城市临界震级</div>
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
</style>
