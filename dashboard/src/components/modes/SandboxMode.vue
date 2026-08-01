<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import echarts from '../../engine/echartsSetup.js'
import { FlaskConical, Loader2, AlertCircle, Sigma, TrendingDown, Gauge, RotateCcw, SlidersHorizontal } from 'lucide-vue-next'
import { useDashboardData } from '../../composables/useDashboardData.js'
import { useMagnitude } from '../../composables/useMagnitude.js'

// ==================== DATA SOURCE ====================
const { data, loading, error } = useDashboardData()
const { currentMag, magnitudes } = useMagnitude()

// 敏感性数据
const sensitivity = computed(() => data.sensitivity || null)

// ==================== INTERACTIVE SANDBOX ====================
// 参数滑块状态：param -> 当前值
const paramValues = reactive({})
// 当前正在交互（拖动/聚焦）的参数 key，用于龙卷风图高亮
const activeParam = ref(null)

// 按类别分组（烈度系数 / 依赖权重 / 崩溃阈值）
const sliderGroups = computed(() => {
  const tornado = sensitivity.value?.tornado || []
  const groups = [
    { name: '烈度系数', key: 'intensity', items: [] },
    { name: '依赖权重', key: 'dependency', items: [] },
    { name: '崩溃阈值', key: 'threshold', items: [] },
  ]
  for (const t of tornado) {
    if (t.param.startsWith('intensity')) groups[0].items.push(t)
    else if (t.param.startsWith('dep')) groups[1].items.push(t)
    else if (t.param.includes('threshold')) groups[2].items.push(t)
  }
  return groups.filter(g => g.items.length > 0)
})

// 初始化（或震级切换后重置）滑块为基准值
function initParamValues() {
  const tornado = sensitivity.value?.tornado
  if (!tornado) return
  for (const t of tornado) {
    paramValues[t.param] = t.base
  }
  activeParam.value = null
}

// 重置全部参数到基准
function resetParams() {
  const tornado = sensitivity.value?.tornado || []
  for (const t of tornado) {
    paramValues[t.param] = t.base
  }
  activeParam.value = null
}

// 滑块步长（约 100 个刻度，最小 0.0001）
function sliderStep(t) {
  const span = t.high - t.low
  if (span <= 0) return 0.001
  return Math.max(span / 100, 0.0001)
}

function formatVal(v) {
  if (v == null || isNaN(v)) return '--'
  return Number(v).toFixed(3)
}

// 滑块轨道填充百分比（用于 CSS 渐变）
function fillPercent(t) {
  const v = paramValues[t.param]
  if (v == null || t.high === t.low) return 0
  return ((v - t.low) / (t.high - t.low)) * 100
}

// 单参数相对基准的偏离百分比
function paramDeviationPct(t) {
  const v = paramValues[t.param]
  if (v == null || t.base === 0) return 0
  return ((v - t.base) / t.base) * 100
}

function deviationClass(t) {
  const d = paramDeviationPct(t)
  if (d > 0.001) return 'text-positive'
  if (d < -0.001) return 'text-negative'
  return 'text-muted'
}

// 单参数对韧性指数的线性影响（OAT 线性插值）
function paramImpact(t) {
  const v = paramValues[t.param]
  if (v == null) return 0
  const { base, low, high, base_resilience, low_resilience, high_resilience } = t
  if (v === base) return 0
  if (v < base) {
    const frac = base - low === 0 ? 0 : (base - v) / (base - low)
    return frac * (low_resilience - base_resilience)
  }
  const frac = high - base === 0 ? 0 : (v - base) / (high - base)
  return frac * (high_resilience - base_resilience)
}

const baseResilience = computed(() => sensitivity.value?.tornado?.[0]?.base_resilience ?? null)

// 综合预测韧性指数（一阶 OAT 叠加，clamp 到 [0,1]）
const estimatedResilience = computed(() => {
  const tornado = sensitivity.value?.tornado
  if (!tornado || tornado.length === 0) return null
  const base = tornado[0].base_resilience
  let delta = 0
  for (const t of tornado) {
    delta += paramImpact(t)
  }
  return Math.max(0, Math.min(1, base + delta))
})

const resilienceDelta = computed(() => {
  if (estimatedResilience.value == null || baseResilience.value == null) return null
  return estimatedResilience.value - baseResilience.value
})

const resilienceDeviationPct = computed(() => {
  if (resilienceDelta.value == null || !baseResilience.value) return 0
  return (resilienceDelta.value / baseResilience.value) * 100
})

const resilienceDeltaClass = computed(() => {
  const d = resilienceDelta.value
  if (d == null) return 'text-muted'
  if (d > 0.0001) return 'text-positive'
  if (d < -0.0001) return 'text-negative'
  return 'text-muted'
})

// 滑块输入处理
function onSliderInput(param, ev) {
  paramValues[param] = parseFloat(ev.target.value)
  activeParam.value = param
}

// 全局敏感性报告（跨震级）
const globalReport = ref(null)
const reportLoading = ref(false)

async function loadGlobalReport() {
  reportLoading.value = true
  try {
    const resp = await fetch('/data/sensitivity_report.json')
    if (resp.ok) {
      globalReport.value = await resp.json()
    }
  } catch (e) {
    console.error('加载敏感性报告失败:', e)
  } finally {
    reportLoading.value = false
  }
}

onMounted(() => {
  initParamValues()
  loadGlobalReport()
  initCharts()
})

onBeforeUnmount(() => {
  destroyCharts()
})

// ==================== CHARTS ====================
const tornadoChartRef = ref(null)
const ciChartRef = ref(null)
const collapseChartRef = ref(null)
const distChartRef = ref(null)

let tornadoChart = null
let ciChart = null
let collapseChart = null
let distChart = null

function initCharts() {
  // 幂等初始化：已 init 的实例不重复创建，仅在 chart 容器已渲染（ref 非空）时补建
  if (tornadoChartRef.value && !tornadoChart) tornadoChart = echarts.init(tornadoChartRef.value)
  if (ciChartRef.value && !ciChart) ciChart = echarts.init(ciChartRef.value)
  if (collapseChartRef.value && !collapseChart) collapseChart = echarts.init(collapseChartRef.value)
  if (distChartRef.value && !distChart) distChart = echarts.init(distChartRef.value)
  updateAllCharts()
}

function destroyCharts() {
  tornadoChart?.dispose()
  ciChart?.dispose()
  collapseChart?.dispose()
  distChart?.dispose()
  tornadoChart = ciChart = collapseChart = distChart = null
}

function updateAllCharts() {
  updateTornadoChart()
  updateCIChart()
  updateCollapseChart()
  updateDistChart()
}

watch([sensitivity, globalReport], () => {
  nextTick(() => {
    initParamValues()
    initCharts() // 幂等：数据就绪、容器渲染后补初始化（修复首次进入时 loading 遮挡导致的图表空白死锁）
    updateAllCharts()
  })
}, { deep: true })

// 拖动滑块时实时高亮龙卷风图对应参数条
watch(activeParam, () => {
  updateTornadoChart()
})

watch(currentMag, () => {
  nextTick(() => updateAllCharts())
})

// ==================== TORNADO CHART ====================
function updateTornadoChart() {
  if (!tornadoChart || !sensitivity.value?.tornado) return

  const tornado = sensitivity.value.tornado
  const baseResilience = tornado[0]?.base_resilience || 0.35
  // 当前交互参数在 tornado 中的索引（-1 表示无高亮）
  const activeIdx = activeParam.value
    ? tornado.findIndex(t => t.param === activeParam.value)
    : -1

  const labels = tornado.map(t => t.label)
  const lowData = tornado.map((t, i) => ({
    value: [t.low_resilience, baseResilience],
    itemStyle: { color: i === activeIdx ? '#FF8A8A' : '#F87171' }
  }))
  const highData = tornado.map((t, i) => ({
    value: [baseResilience, t.high_resilience],
    itemStyle: { color: i === activeIdx ? '#5EEAB6' : '#34D399' }
  }))

  tornadoChart.setOption({
    backgroundColor: 'transparent',
    grid: { left: 140, right: 60, top: 30, bottom: 30 },
    xAxis: {
      type: 'value',
      min: 0.2,
      max: 0.5,
      axisLine: { lineStyle: { color: '#1C2B43' } },
      axisLabel: { color: '#7E91AC', fontSize: 11 },
      splitLine: { lineStyle: { color: '#16243C' } },
      name: '韧性指数',
      nameLocation: 'middle',
      nameGap: 25,
      nameTextStyle: { color: '#7E91AC', fontSize: 11 },
    },
    yAxis: {
      type: 'category',
      data: labels,
      axisLine: { lineStyle: { color: '#1C2B43' } },
      axisLabel: {
        formatter: (value, index) => index === activeIdx ? `{a|${value}}` : `{n|${value}}`,
        rich: {
          a: { color: '#00D4FF', fontSize: 13, fontWeight: 'bold' },
          n: { color: '#E6EDF7', fontSize: 12 },
        },
      },
      inverse: true,
    },
    series: [
      {
        name: '低值',
        type: 'custom',
        renderItem: (params, api) => {
          const isActive = params.dataIndex === activeIdx
          const start = api.coord([api.value(0), api.value(1)])
          const end = api.coord([api.value(1), api.value(1)])
          const h = isActive ? 22 : 16
          const baseStyle = api.visual('style')
          return {
            type: 'rect',
            shape: { x: start[0], y: start[1] - h / 2, width: end[0] - start[0], height: h },
            style: isActive
              ? { ...baseStyle, shadowBlur: 16, shadowColor: api.visual('color') }
              : baseStyle,
          }
        },
        encode: { x: [0, 1], y: 1 },
        data: lowData,
      },
      {
        name: '高值',
        type: 'custom',
        renderItem: (params, api) => {
          const isActive = params.dataIndex === activeIdx
          const start = api.coord([api.value(0), api.value(1)])
          const end = api.coord([api.value(1), api.value(1)])
          const h = isActive ? 22 : 16
          const baseStyle = api.visual('style')
          return {
            type: 'rect',
            shape: { x: start[0], y: start[1] - h / 2, width: end[0] - start[0], height: h },
            style: isActive
              ? { ...baseStyle, shadowBlur: 16, shadowColor: api.visual('color') }
              : baseStyle,
          }
        },
        encode: { x: [0, 1], y: 1 },
        data: highData,
      },
      {
        name: '基准线',
        type: 'line',
        data: labels.map(() => baseResilience),
        symbol: 'none',
        lineStyle: { color: '#00D4FF', width: 2, type: 'dashed' },
        markPoint: {
          data: [{ coord: [baseResilience, 0], symbol: 'none' }],
        },
      },
    ],
    tooltip: {
      trigger: 'item',
      formatter: (p) => {
        const t = tornado[p.dataIndex]
        if (!t) return ''
        return `<b>${t.label}</b><br/>` +
               `低值: ${t.low_resilience.toFixed(4)} (参数=${t.low.toFixed(3)})<br/>` +
               `高值: ${t.high_resilience.toFixed(4)} (参数=${t.high.toFixed(3)})<br/>` +
               `范围: ${t.resilience_range.toFixed(4)}`
      },
    },
  })
}

// ==================== CONFIDENCE INTERVAL CHART ====================
function updateCIChart() {
  if (!ciChart || !sensitivity.value?.system_confidence_intervals) return

  const ci = sensitivity.value.system_confidence_intervals

  ciChart.setOption({
    backgroundColor: 'transparent',
    grid: { left: 60, right: 60, top: 30, bottom: 40 },
    xAxis: {
      type: 'category',
      data: ci.map(s => s.name),
      axisLine: { lineStyle: { color: '#1C2B43' } },
      axisLabel: { color: '#E6EDF7', fontSize: 13 },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 1,
      axisLine: { lineStyle: { color: '#1C2B43' } },
      axisLabel: { color: '#7E91AC', fontSize: 11, formatter: '{value}' },
      splitLine: { lineStyle: { color: '#16243C' } },
      name: '功能率',
      nameLocation: 'middle',
      nameGap: 35,
      nameTextStyle: { color: '#7E91AC', fontSize: 11 },
    },
    series: [
      {
        name: 'P5-P95 置信区间',
        type: 'custom',
        renderItem: (params, api) => {
          const p5 = api.coord([api.value(0), api.value(1)])
          const p95 = api.coord([api.value(0), api.value(2)])
          const mean = api.coord([api.value(0), api.value(3)])
          return {
            type: 'group',
            children: [
              { type: 'rect', shape: { x: p5[0] - 15, y: p95[1], width: 30, height: p5[1] - p95[1] },
                style: { fill: api.visual('color'), opacity: 0.2 } },
              { type: 'line', shape: { x1: p5[0] - 15, y1: p95[1], x2: p5[0] + 15, y2: p95[1] },
                style: { stroke: api.visual('color'), lineWidth: 2 } },
              { type: 'line', shape: { x1: p5[0] - 15, y1: p5[1], x2: p5[0] + 15, y2: p5[1] },
                style: { stroke: api.visual('color'), lineWidth: 2 } },
              { type: 'line', shape: { x1: p5[0], y1: p95[1], x2: p5[0], y2: p5[1] },
                style: { stroke: api.visual('color'), lineWidth: 1, opacity: 0.5 } },
              { type: 'circle', shape: { cx: mean[0], cy: mean[1], r: 5 },
                style: { fill: api.visual('color') } },
            ],
          }
        },
        encode: { x: 0, y: [1, 2, 3] },
        data: ci.map((s, i) => ({
          value: [i, s.p5, s.p95, s.mean],
          itemStyle: { color: s.color },
        })),
      },
    ],
    tooltip: {
      trigger: 'item',
      formatter: (p) => {
        const s = ci[p.dataIndex]
        if (!s) return ''
        return `<b>${s.name}系统</b><br/>` +
               `均值: ${s.mean.toFixed(4)}<br/>` +
               `标准差: ${s.std.toFixed(4)}<br/>` +
               `90% CI: [${s.p5.toFixed(4)}, ${s.p95.toFixed(4)}]`
      },
    },
  })
}

// ==================== COLLAPSE PROBABILITY CHART ====================
function updateCollapseChart() {
  if (!collapseChart) return

  let probs = {}
  if (globalReport.value?.monte_carlo?.collapse_probabilities) {
    probs = globalReport.value.monte_carlo.collapse_probabilities
  } else if (sensitivity.value) {
    const mk = `M${currentMag.value.toFixed(1)}`
    probs[mk] = sensitivity.value.collapse_probability
  }

  const mags = magnitudes.map(m => `M${m.toFixed(1)}`)
  const values = magnitudes.map(m => {
    const key = `M${m.toFixed(1)}`
    return probs[key] || 0
  })

  collapseChart.setOption({
    backgroundColor: 'transparent',
    grid: { left: 60, right: 30, top: 30, bottom: 40 },
    xAxis: {
      type: 'category',
      data: mags,
      axisLine: { lineStyle: { color: '#1C2B43' } },
      axisLabel: { color: '#7E91AC', fontSize: 11 },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 1,
      axisLine: { lineStyle: { color: '#1C2B43' } },
      axisLabel: { color: '#7E91AC', fontSize: 11, formatter: '{value*100}%' },
      splitLine: { lineStyle: { color: '#16243C' } },
    },
    series: [{
      type: 'bar',
      data: values.map(v => ({
        value: v,
        itemStyle: {
          color: v > 0.95 ? '#F87171' : v > 0.5 ? '#FBBF24' : '#34D399',
          borderRadius: [4, 4, 0, 0],
        }
      })),
      barWidth: '50%',
      label: {
        show: true,
        position: 'top',
        color: '#E6EDF7',
        fontSize: 11,
        formatter: (p) => `${(p.value * 100).toFixed(1)}%`,
      },
    }],
    tooltip: {
      trigger: 'item',
      formatter: (p) => `${p.name}<br/>崩溃概率: ${(p.value * 100).toFixed(1)}%`,
    },
  })
}

// ==================== DISTRIBUTION CHART ====================
function updateDistChart() {
  if (!distChart) return

  let dist = null
  if (globalReport.value?.monte_carlo?.threshold_magnitude_distribution) {
    dist = globalReport.value.monte_carlo.threshold_magnitude_distribution
  } else if (sensitivity.value?.threshold_distribution) {
    dist = sensitivity.value.threshold_distribution
  }

  if (!dist) return

  // 从 values 构建直方图
  const values = dist.values || []
  const bins = {}
  for (const v of values) {
    const key = `M${v.toFixed(1)}`
    bins[key] = (bins[key] || 0) + 1
  }
  const sortedKeys = Object.keys(bins).sort((a, b) => {
    return parseFloat(a.slice(1)) - parseFloat(b.slice(1))
  })

  distChart.setOption({
    backgroundColor: 'transparent',
    grid: { left: 60, right: 30, top: 30, bottom: 40 },
    xAxis: {
      type: 'category',
      data: sortedKeys,
      axisLine: { lineStyle: { color: '#1C2B43' } },
      axisLabel: { color: '#7E91AC', fontSize: 11 },
    },
    yAxis: {
      type: 'value',
      axisLine: { lineStyle: { color: '#1C2B43' } },
      axisLabel: { color: '#7E91AC', fontSize: 11 },
      splitLine: { lineStyle: { color: '#16243C' } },
      name: '频次',
      nameLocation: 'middle',
      nameGap: 35,
      nameTextStyle: { color: '#7E91AC', fontSize: 11 },
    },
    series: [{
      type: 'bar',
      data: sortedKeys.map(k => ({
        value: bins[k],
        itemStyle: {
          color: '#A78BFA',
          borderRadius: [4, 4, 0, 0],
        }
      })),
      barWidth: '60%',
      markLine: {
        data: [
          { xAxis: `M${dist.median.toFixed(1)}`, label: { formatter: '中位数', color: '#00D4FF' },
            lineStyle: { color: '#00D4FF', width: 2, type: 'dashed' } },
        ],
      },
    }],
    tooltip: {
      trigger: 'item',
      formatter: (p) => `${p.name}<br/>频次: ${p.value}`,
    },
  })
}

// ==================== COMPUTED ====================
const collapseProb = computed(() => {
  if (!sensitivity.value) return 0
  return sensitivity.value.collapse_probability || 0
})

const paramImportance = computed(() => {
  if (!sensitivity.value?.parameter_importance) return []
  return sensitivity.value.parameter_importance
})

const nSamples = computed(() => {
  return sensitivity.value?.n_samples || globalReport.value?.meta?.n_samples || 500
})

const thresholdDist = computed(() => {
  if (globalReport.value?.monte_carlo?.threshold_magnitude_distribution) {
    return globalReport.value.monte_carlo.threshold_magnitude_distribution
  }
  return sensitivity.value?.threshold_distribution || null
})

// 窗口resize
function handleResize() {
  tornadoChart?.resize()
  ciChart?.resize()
  collapseChart?.resize()
  distChart?.resize()
}

onMounted(() => {
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
})
</script>

<template>
  <div class="sandbox-mode">
    <!-- Loading -->
    <div v-if="loading" class="loading-state">
      <Loader2 :size="32" class="spin" />
      <span>加载敏感性数据...</span>
    </div>

    <!-- Error -->
    <div v-else-if="error" class="error-state">
      <AlertCircle :size="32" />
      <span>{{ error }}</span>
    </div>

    <!-- Empty -->
    <div v-else-if="!sensitivity" class="empty-state">
      <FlaskConical :size="32" />
      <span>当前震级无敏感性数据</span>
    </div>

    <!-- Content -->
    <template v-else>
      <!-- Header Stats -->
      <div class="stats-bar">
        <div class="stat-item">
          <div class="stat-icon"><Sigma :size="16" /></div>
          <div class="stat-content">
            <div class="stat-label">蒙特卡洛采样</div>
            <div class="stat-value">{{ nSamples }} <span class="unit">次</span></div>
          </div>
        </div>
        <div class="stat-item">
          <div class="stat-icon" :class="{ 'stat-danger': collapseProb > 0.9 }">
            <TrendingDown :size="16" />
          </div>
          <div class="stat-content">
            <div class="stat-label">崩溃概率 M{{ currentMag.toFixed(1) }}</div>
            <div class="stat-value" :class="{ 'text-danger': collapseProb > 0.9 }">
              {{ (collapseProb * 100).toFixed(1) }}<span class="unit">%</span>
            </div>
          </div>
        </div>
        <div class="stat-item" v-if="thresholdDist">
          <div class="stat-icon"><Gauge :size="16" /></div>
          <div class="stat-content">
            <div class="stat-label">临界震级分布</div>
            <div class="stat-value">
              M{{ thresholdDist.mean.toFixed(2) }}
              <span class="unit">±{{ thresholdDist.std.toFixed(2) }}</span>
            </div>
          </div>
        </div>
        <div class="stat-item" v-if="thresholdDist">
          <div class="stat-icon"><Gauge :size="16" /></div>
          <div class="stat-content">
            <div class="stat-label">90% 置信区间</div>
            <div class="stat-value">
              [M{{ thresholdDist.p5.toFixed(1) }}, M{{ thresholdDist.p95.toFixed(1) }}]
            </div>
          </div>
        </div>
      </div>

      <!-- Main Grid -->
      <div class="sandbox-grid">
        <!-- Interactive Parameter Sandbox -->
        <div class="panel panel-sandbox">
          <div class="panel-header">
            <div class="panel-title-group">
              <SlidersHorizontal :size="16" class="title-icon" />
              <div>
                <div class="panel-title">参数交互沙盘</div>
                <div class="panel-sub">拖动滑块模拟参数变化 · 实时预测韧性指数（一阶 OAT 叠加）</div>
              </div>
            </div>
            <button class="reset-btn" @click="resetParams">
              <RotateCcw :size="14" />
              <span>重置基准</span>
            </button>
          </div>

          <!-- Resilience Summary -->
          <div class="resilience-summary">
            <div class="summary-item">
              <span class="summary-label">预测韧性指数</span>
              <span class="summary-value" :class="resilienceDeltaClass">
                {{ estimatedResilience != null ? estimatedResilience.toFixed(4) : '--' }}
              </span>
            </div>
            <div class="summary-item">
              <span class="summary-label">基准韧性指数</span>
              <span class="summary-value muted">{{ baseResilience != null ? baseResilience.toFixed(4) : '--' }}</span>
            </div>
            <div class="summary-item">
              <span class="summary-label">偏移 Δ</span>
              <span class="summary-value" :class="resilienceDeltaClass">
                <template v-if="resilienceDelta != null">
                  {{ resilienceDelta >= 0 ? '+' : '' }}{{ resilienceDelta.toFixed(4) }}
                  <span class="summary-delta-pct">
                    ({{ resilienceDeviationPct >= 0 ? '+' : '' }}{{ resilienceDeviationPct.toFixed(2) }}%)
                  </span>
                </template>
                <template v-else>--</template>
              </span>
            </div>
          </div>

          <!-- Slider Groups -->
          <div class="slider-groups">
            <div class="slider-group" v-for="group in sliderGroups" :key="group.key">
              <div class="group-title">{{ group.name }}</div>
              <div
                v-for="t in group.items"
                :key="t.param"
                class="slider-card"
                :class="{ active: activeParam === t.param }"
              >
                <div class="slider-card-head">
                  <span class="slider-label">{{ t.label }}</span>
                  <span class="slider-values">
                    <span class="slider-current">{{ formatVal(paramValues[t.param]) }}</span>
                    <span class="slider-base">基准 {{ formatVal(t.base) }}</span>
                  </span>
                </div>
                <input
                  type="range"
                  class="param-slider"
                  :min="t.low"
                  :max="t.high"
                  :step="sliderStep(t)"
                  :value="paramValues[t.param]"
                  :style="{ '--fill': fillPercent(t) + '%' }"
                  @input="onSliderInput(t.param, $event)"
                  @focus="activeParam = t.param"
                />
                <div class="slider-card-foot">
                  <span class="deviation" :class="deviationClass(t)">
                    偏离 {{ paramDeviationPct(t) >= 0 ? '+' : '' }}{{ paramDeviationPct(t).toFixed(2) }}%
                  </span>
                  <span class="impact">
                    韧性影响
                    <span :class="paramImpact(t) > 0 ? 'text-positive' : paramImpact(t) < 0 ? 'text-negative' : 'text-muted'">
                      {{ paramImpact(t) >= 0 ? '+' : '' }}{{ paramImpact(t).toFixed(4) }}
                    </span>
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Tornado Chart -->
        <div class="panel panel-tornado">
          <div class="panel-header">
            <span class="panel-title">参数敏感性龙卷风图</span>
            <span class="panel-sub">OAT ±20% · 基准韧性指数 = {{ sensitivity.tornado?.[0]?.base_resilience?.toFixed(4) }}</span>
          </div>
          <div ref="tornadoChartRef" class="chart-area" style="height: 320px;"></div>
          <div class="legend-row">
            <span class="legend-item"><span class="dot red"></span>参数低值（韧性下降）</span>
            <span class="legend-item"><span class="dot green"></span>参数高值（韧性上升）</span>
            <span class="legend-item"><span class="dot cyan"></span>基准线</span>
          </div>
        </div>

        <!-- Confidence Intervals -->
        <div class="panel panel-ci">
          <div class="panel-header">
            <span class="panel-title">系统功能率置信区间</span>
            <span class="panel-sub">M{{ currentMag.toFixed(1) }} · 500次MC采样</span>
          </div>
          <div ref="ciChartRef" class="chart-area" style="height: 280px;"></div>
        </div>

        <!-- Collapse Probability -->
        <div class="panel panel-collapse">
          <div class="panel-header">
            <span class="panel-title">城市崩溃概率（跨震级）</span>
            <span class="panel-sub">蒙特卡洛模拟</span>
          </div>
          <div ref="collapseChartRef" class="chart-area" style="height: 240px;"></div>
        </div>

        <!-- Distribution -->
        <div class="panel panel-dist">
          <div class="panel-header">
            <span class="panel-title">崩溃临界震级分布</span>
            <span class="panel-sub" v-if="thresholdDist">
              均值 M{{ thresholdDist.mean.toFixed(2) }} · 中位数 M{{ thresholdDist.median.toFixed(2) }}
            </span>
          </div>
          <div ref="distChartRef" class="chart-area" style="height: 240px;"></div>
        </div>

        <!-- Parameter Importance -->
        <div class="panel panel-importance">
          <div class="panel-header">
            <span class="panel-title">参数重要性排名</span>
            <span class="panel-sub">Spearman 秩相关 ρ</span>
          </div>
          <div class="importance-list">
            <div
              v-for="(p, i) in paramImportance"
              :key="p.param"
              class="importance-row"
              :class="{ significant: p.significant }"
            >
              <span class="rank">#{{ i + 1 }}</span>
              <span class="param-label">{{ p.label }}</span>
              <div class="rho-bar-container">
                <div
                  class="rho-bar"
                  :class="p.rho > 0 ? 'positive' : 'negative'"
                  :style="{ width: Math.abs(p.rho) * 100 + '%' }"
                ></div>
              </div>
              <span class="rho-value" :class="p.rho > 0 ? 'text-positive' : 'text-negative'">
                {{ p.rho > 0 ? '+' : '' }}{{ p.rho.toFixed(4) }}
              </span>
              <span class="sig-badge" v-if="p.significant">p&lt;0.05</span>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.sandbox-mode {
  height: 100%;
  overflow-y: auto;
  padding: 16px;
}

.loading-state,
.error-state,
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  height: 100%;
  color: var(--muted);
  font-size: var(--text-body);
}

.spin {
  animation: spin 1s linear infinite;
  color: var(--primary);
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Stats Bar */
.stats-bar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 10px 16px;
  flex: 1;
  min-width: 180px;
}

.stat-icon {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  background: var(--primary-dim);
  color: var(--primary);
}

.stat-icon.stat-danger {
  background: var(--error-dim);
  color: var(--error);
}

.stat-label {
  font-size: var(--text-caption);
  color: var(--muted);
  margin-bottom: 2px;
}

.stat-value {
  font-size: var(--text-title);
  font-weight: 600;
  color: var(--ink);
  font-family: var(--font-mono);
}

.text-danger {
  color: var(--error);
}

.unit {
  font-size: var(--text-caption);
  color: var(--muted);
  font-weight: 400;
}

/* Grid */
.sandbox-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.panel-tornado {
  grid-column: 1 / -1;
}

.panel-importance {
  grid-column: 1 / -1;
}

/* Panel */
.panel {
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 14px;
  display: flex;
  flex-direction: column;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 8px;
}

.panel-title {
  font-size: var(--text-body);
  font-weight: 600;
  color: var(--ink);
}

.panel-sub {
  font-size: var(--text-caption);
  color: var(--muted);
}

.chart-area {
  width: 100%;
}

/* Legend */
.legend-row {
  display: flex;
  gap: 16px;
  justify-content: center;
  padding-top: 8px;
  border-top: 1px solid var(--border);
  margin-top: 4px;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-caption);
  color: var(--muted);
}

.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.dot.red { background: var(--error); }
.dot.green { background: var(--success); }
.dot.cyan { background: var(--primary); }

/* Importance List */
.importance-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 4px;
}

.importance-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  background: var(--bg3);
  border-radius: var(--radius-sm);
  border-left: 3px solid transparent;
  transition: border-color 0.2s;
}

.importance-row.significant {
  border-left-color: var(--primary);
}

.rank {
  font-size: var(--text-caption);
  color: var(--muted);
  font-family: var(--font-mono);
  width: 28px;
  flex-shrink: 0;
}

.param-label {
  font-size: var(--text-body);
  color: var(--ink);
  width: 140px;
  flex-shrink: 0;
}

.rho-bar-container {
  flex: 1;
  height: 8px;
  background: var(--bg);
  border-radius: var(--radius-full);
  overflow: hidden;
  position: relative;
}

.rho-bar {
  height: 100%;
  border-radius: var(--radius-full);
  transition: width 0.6s ease;
}

.rho-bar.positive {
  background: var(--success);
}

.rho-bar.negative {
  background: var(--error);
}

.rho-value {
  font-size: var(--text-code);
  font-family: var(--font-mono);
  width: 60px;
  text-align: right;
  flex-shrink: 0;
}

.text-positive {
  color: var(--success);
}

.text-negative {
  color: var(--error);
}

.sig-badge {
  font-size: var(--text-micro);
  padding: 2px 6px;
  border-radius: var(--radius-sm);
  background: var(--primary-dim);
  color: var(--primary);
  flex-shrink: 0;
}

/* ==================== Interactive Sandbox ==================== */
.panel-sandbox {
  grid-column: 1 / -1;
}

.panel-title-group {
  display: flex;
  align-items: center;
  gap: 10px;
}

.title-icon {
  color: var(--primary);
  flex-shrink: 0;
}

.reset-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: var(--primary-dim);
  border: 1px solid var(--primary-border);
  border-radius: var(--radius-sm);
  color: var(--primary);
  font-size: var(--text-caption);
  font-family: var(--font-sans);
  cursor: pointer;
  transition: all 0.2s;
}

.reset-btn:hover {
  background: var(--primary);
  color: var(--primary-fg);
  box-shadow: 0 0 12px rgba(0, 212, 255, 0.4);
}

/* Resilience Summary */
.resilience-summary {
  display: flex;
  gap: 28px;
  padding: 12px 16px;
  background: var(--bg3);
  border-radius: var(--radius-md);
  border: 1px solid var(--border);
  margin: 10px 0 14px;
  flex-wrap: wrap;
}

.summary-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.summary-label {
  font-size: var(--text-caption);
  color: var(--muted);
}

.summary-value {
  font-size: var(--text-title);
  font-weight: 600;
  font-family: var(--font-mono);
  color: var(--ink);
  display: flex;
  align-items: baseline;
  gap: 4px;
}

.summary-value.muted {
  color: var(--muted);
}

.summary-delta-pct {
  font-size: var(--text-caption);
  color: var(--muted);
  font-weight: 400;
}

/* Slider Groups */
.slider-groups {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.slider-group {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.group-title {
  font-size: var(--text-caption);
  font-weight: 600;
  color: var(--primary);
  letter-spacing: 1px;
  padding-bottom: 4px;
  border-bottom: 1px solid var(--primary-border);
}

.slider-card {
  background: var(--bg3);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 10px 12px;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.slider-card.active {
  border-color: var(--primary);
  box-shadow: 0 0 0 1px var(--primary-border), 0 0 16px rgba(0, 212, 255, 0.25);
}

.slider-card-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 8px;
}

.slider-label {
  font-size: var(--text-body);
  color: var(--ink);
}

.slider-values {
  display: flex;
  align-items: baseline;
  gap: 6px;
  font-family: var(--font-mono);
}

.slider-current {
  font-size: var(--text-code);
  font-weight: 600;
  color: var(--primary);
}

.slider-base {
  font-size: var(--text-micro);
  color: var(--muted);
}

/* Range Slider — dark tech theme */
.param-slider {
  -webkit-appearance: none;
  appearance: none;
  width: 100%;
  height: 4px;
  border-radius: var(--radius-full);
  background: linear-gradient(
    to right,
    var(--primary) 0%,
    var(--primary) var(--fill, 0%),
    var(--border) var(--fill, 0%),
    var(--border) 100%
  );
  outline: none;
  cursor: pointer;
  margin: 4px 0;
}

.param-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--primary);
  border: 2px solid var(--bg);
  cursor: pointer;
  box-shadow: 0 0 8px rgba(0, 212, 255, 0.7);
  transition: box-shadow 0.2s, transform 0.1s;
}

.param-slider::-webkit-slider-thumb:hover,
.param-slider:focus::-webkit-slider-thumb {
  box-shadow: 0 0 14px rgba(0, 212, 255, 1);
  transform: scale(1.15);
}

.param-slider::-moz-range-thumb {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--primary);
  border: 2px solid var(--bg);
  cursor: pointer;
  box-shadow: 0 0 8px rgba(0, 212, 255, 0.7);
}

.param-slider::-moz-range-track {
  background: transparent;
}

.slider-card-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 6px;
}

.deviation {
  font-family: var(--font-mono);
  font-size: var(--text-micro);
}

.impact {
  font-size: var(--text-micro);
  color: var(--muted);
  font-family: var(--font-mono);
}

.text-muted {
  color: var(--muted);
}

@media (max-width: 900px) {
  .slider-groups {
    grid-template-columns: 1fr;
  }
  .resilience-summary {
    gap: 16px;
  }
}
</style>
