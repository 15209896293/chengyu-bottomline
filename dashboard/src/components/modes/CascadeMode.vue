<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import echarts from '../../engine/echartsSetup.js'
import { Zap, GitBranch, Share2, Route, X, Loader2, Play, Pause, Clock } from 'lucide-vue-next'
import { useDashboardData } from '../../composables/useDashboardData.js'
import { useMagnitude } from '../../composables/useMagnitude.js'

// ==================== DATA SOURCE ====================
const { data, loading, error, allCascade, loadAllCascadeSummary } = useDashboardData()
const { currentMag, magnitudes } = useMagnitude()

// 系统节点固定布局坐标
const NODE_POSITIONS = {
  medical:   { x: 250, y: 80  },
  transport: { x: 150, y: 210 },
  rescue:    { x: 350, y: 210 },
  shelter:   { x: 250, y: 260 },
}

const RADIUS = 30
const NODE_KEYS = ['medical', 'transport', 'rescue', 'shelter']
const SYSTEM_LABELS = ['医', '交', '救', '避']

// ==================== COMPUTED: CASCADE DATA ====================

// 从 JSON 加载的 cascade 数据
const cascade = computed(() => data.cascade || null)

// 依赖矩阵
const depMatrix = computed(() => cascade.value?.dependency_matrix || [
  [1.00, 0.45, 0.20, 0.38],
  [0.45, 1.00, 0.55, 0.20],
  [0.20, 0.55, 1.00, 0.52],
  [0.38, 0.20, 0.52, 1.00],
])

// 4 个系统节点（从 JSON cascade.systems 动态计算）
const nodes = computed(() => {
  if (!cascade.value?.systems) {
    // 默认值
    return {}
  }
  const result = {}
  for (const key of NODE_KEYS) {
    const sys = cascade.value.systems[key]
    if (!sys) continue
    const pos = NODE_POSITIONS[key]
    result[key] = {
      name: sys.name,
      x: pos.x,
      y: pos.y,
      color: sys.color,
      status: sys.status,
      value: Math.round(sys.cascade_ratio * 1000) / 10,
      collapsed: sys.collapsed,
      cascadeRatio: sys.cascade_ratio,
      baseRatio: sys.base_ratio,
      cascadeDrop: sys.cascade_drop,
    }
  }
  return result
})

// 依赖边（对称矩阵的 6 条唯一边）
const depPairs = [
  ['medical', 'transport'],
  ['medical', 'rescue'],
  ['medical', 'shelter'],
  ['transport', 'rescue'],
  ['transport', 'shelter'],
  ['rescue', 'shelter'],
]

// 计算两点间边缘端点
function edgeGeometry(sKey, tKey) {
  const S = NODE_POSITIONS[sKey], T = NODE_POSITIONS[tKey]
  const dx = T.x - S.x, dy = T.y - S.y
  const len = Math.max(0.001, Math.hypot(dx, dy))
  const ux = dx / len, uy = dy / len
  return {
    sx: S.x + RADIUS * ux,
    sy: S.y + RADIUS * uy,
    ex: T.x - (RADIUS + 6) * ux,
    ey: T.y - (RADIUS + 6) * uy
  }
}

// 获取依赖权重
function getDepWeight(sKey, tKey) {
  const order = NODE_KEYS
  const i = order.indexOf(sKey)
  const j = order.indexOf(tKey)
  if (i < 0 || j < 0) return 0
  const m = depMatrix.value
  if (!m || !m[i] || m[i][j] === undefined) return 0
  return m[i][j]
}

// 依赖边几何数据
const depEdges = computed(() => {
  return depPairs.map(([s, t]) => {
    const w = getDepWeight(s, t)
    return {
      s, t, w,
      ...edgeGeometry(s, t),
      width: (w * 5 + 1).toFixed(1)
    }
  })
})

// 传播路径（从 cascade_timeline 提取）
const propSegments = computed(() => {
  const timeline = cascade.value?.cascade_timeline
  if (!timeline || timeline.length < 2) return []
  const segs = []
  for (let i = 0; i < timeline.length - 1; i++) {
    const src = timeline[i].system
    const tgt = timeline[i + 1].system
    if (NODE_POSITIONS[src] && NODE_POSITIONS[tgt]) {
      segs.push({
        ...edgeGeometry(src, tgt),
        from: nodes.value[src]?.name || src,
        to: nodes.value[tgt]?.name || tgt
      })
    }
  }
  return segs
})

// 节点状态标签位置
function statusPos(sys) {
  const n = NODE_POSITIONS[sys]
  if (sys === 'medical') return { x: n.x, y: n.y - RADIUS - 8 }
  return { x: n.x, y: n.y + RADIUS + 14 }
}

// ==================== 交互：节点高亮 ====================
const selectedNode = ref(null)

function toggleNode(sys) {
  selectedNode.value = selectedNode.value === sys ? null : sys
}

function clearSelection() {
  selectedNode.value = null
}

function isEdgeHi(edge) {
  if (!selectedNode.value) return false
  return edge.s === selectedNode.value || edge.t === selectedNode.value
}

function isEdgeDim(edge) {
  if (!selectedNode.value) return false
  return !isEdgeHi(edge)
}

// ==================== KPI Bar ====================
const kpiItems = computed(() => {
  const c = cascade.value
  if (!c) return []
  const sys = c.systems || {}
  const magStr = `M${currentMag.value.toFixed(1)}`
  return [
    { label: '当前震级', value: magStr, color: 'accent' },
    { label: '医疗', value: sys.medical ? `${(sys.medical.cascade_ratio * 100).toFixed(1)}%` : 'N/A', color: sys.medical?.collapsed ? 'red' : 'green' },
    { label: '救援', value: sys.rescue ? `${(sys.rescue.cascade_ratio * 100).toFixed(1)}%` : 'N/A', color: sys.rescue?.collapsed ? 'red' : 'orange' },
    { label: '交通', value: sys.transport ? `${(sys.transport.cascade_ratio * 100).toFixed(1)}%` : 'N/A', color: 'yellow' },
    { label: '避难', value: sys.shelter ? `${(sys.shelter.cascade_ratio * 100).toFixed(1)}%` : 'N/A', color: sys.shelter?.collapsed ? 'red' : 'green' },
    { label: '级联深度', value: `${c.cascade_depth || 0}层`, color: 'accent' },
    { label: '传播路径', value: `${c.propagation_paths_count || 0}条`, color: 'accent' },
    { label: '韧性指数', value: data.charts?.resilience?.resilience_index?.toFixed(3) || 'N/A', color: 'yellow' },
  ]
})

// ==================== 级联传播链 ====================
const chainNodes = computed(() => {
  const timeline = cascade.value?.cascade_timeline
  if (!timeline) return []
  return timeline.map(t => {
    const sys = cascade.value?.systems?.[t.system]
    const ratio = t.ratio || (sys?.cascade_ratio || 0)
    return {
      key: t.system,
      name: sys?.name || t.system,
      state: sys?.status || t.event,
      value: Math.round(ratio * 1000) / 10,
      color: sys?.color || '#7E91AC',
    }
  })
})

// 相邻节点间传播概率：按 timeline 序列顺序取 prop_strengths 中 source→target 匹配的权重
// 修正原 chainProbs 错配（prop_strengths 的顺序/语义与 timeline 序列不同导致概率标错边）
const chainEdgeProbs = computed(() => {
  const strengths = cascade.value?.prop_strengths || []
  const nodes = chainNodes.value
  const edges = []
  for (let i = 0; i < nodes.length - 1; i++) {
    const prev = nodes[i].key
    const next = nodes[i + 1].key
    // 在 prop_strengths 中找 prev→next 或 next→prev 的边
    const match = strengths.find(s => (s.source === prev && s.target === next) || (s.source === next && s.target === prev))
    // 找不到明确依赖边时，用该节点 cascade_drop 体现传播损耗
    const drop = cascade.value?.systems?.[next]?.cascade_drop
    edges.push(match ? Math.round((match.weight || match.pct / 100 || 0) * 100) : (drop != null ? Math.round(drop * 100) : 0))
  }
  return edges
})

// ==================== 关键脆弱节点 ====================
const vulnNodes = computed(() => {
  return cascade.value?.vulnerable_nodes || []
})

// ==================== 影响范围 ====================
const impactData = computed(() => {
  return cascade.value?.impact_data || []
})

// ==================== 传播强度条 ====================
const propStrengths = computed(() => {
  return cascade.value?.prop_strengths || []
})

// ==================== 矩阵着色 ====================
function depCellColor(w) {
  return `rgba(0,212,255,${w.toFixed(2)})`
}

function depCellTxtColor(i, j, w) {
  if (i === j) return 'var(--av-primary)'
  return w > 0.5 ? '#fff' : (w > 0.01 ? '#cdd6e4' : '#5a6c8a')
}

// ==================== 热力图 SVG 参数 ====================
const HM_CELL = 32, HM_OX = 32, HM_OY = 28

// ==================== 状态横幅 ====================
const statusBanner = computed(() => {
  const c = cascade.value
  if (!c) return { title: '加载中...', desc: '', color: '#7E91AC', bg: 'rgba(126,145,172,0.15)' }
  const magStr = `M${currentMag.value.toFixed(1)}`
  if (c.city_cascade_collapse) {
    // 按级联时序列出崩溃系统，与真实传播链顺序一致（systems 对象键序与 timeline 不同）
    const timelineOrder = Array.isArray(c.cascade_timeline) ? c.cascade_timeline.map(t => t.system) : []
    const collapsedSys = (timelineOrder.length
      ? timelineOrder
      : Object.keys(c.systems || {})
    )
      .filter(k => c.systems?.[k]?.collapsed)
      .map(k => c.systems?.[k]?.name || k)
      .join('→')
    return {
      title: `${magStr} 级联传播中`,
      desc: collapsedSys + '崩溃',
      color: 'var(--state-error)',
      bg: 'rgba(248,113,113,0.15)',
      borderColor: 'rgba(248,113,113,0.3)'
    }
  }
  return {
    title: `${magStr} 系统承压`,
    desc: '尚未触发级联崩溃',
    color: 'var(--state-warning)',
    bg: 'rgba(251,191,36,0.15)',
    borderColor: 'rgba(251,191,36,0.3)'
  }
})

// ==================== ECharts 折线图 ====================
const chartRef = ref(null)
let chartInstance = null
let resizeObserver = null

function initChart() {
  if (!chartRef.value) return
  chartInstance = echarts.init(chartRef.value)
  updateChart()
}

function updateChart() {
  if (!chartInstance) return

  const magLabels = magnitudes.map(m => 'M' + m.toFixed(1))

  // 系统崩溃阈值 > 从 JSON 读取，避免与算法脚本不同步
  const sys = cascade.value?.systems || {}
  const thCollapse = {
    medical: sys.medical?.collapse_threshold ?? 0.30,
    rescue: sys.rescue?.collapse_threshold ?? 0.40,
    transport: sys.transport?.collapse_threshold ?? 0.50,
    shelter: sys.shelter?.collapse_threshold ?? 0.30,
  }

  // 使用 allCascade 汇总数据，如果未加载则用默认值
  const chartData = allCascade.value.length > 0 ? allCascade.value : magnitudes.map(m => {
    const sys = cascade.value?.systems || {}
    return {
      medical: sys.medical?.cascade_ratio || 0,
      rescue: sys.rescue?.cascade_ratio || 0,
      transport: sys.transport?.cascade_ratio || 0,
      shelter: sys.shelter?.cascade_ratio || 0,
    }
  })

  chartInstance.setOption({
    grid: { left: 36, right: 14, top: 28, bottom: 22 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#142440',
      borderColor: '#1C2B43',
      borderWidth: 1,
      textStyle: { color: '#E6EDF7', fontSize: 10 },
      formatter(params) {
        let s = params[0].axisValue + '<br/>'
        params.forEach(p => {
          s += p.marker + p.seriesName + ': ' + (p.value * 100).toFixed(1) + '%<br/>'
        })
        return s
      }
    },
    legend: {
      top: 0,
      right: 0,
      textStyle: { color: '#7E91AC', fontSize: 9 },
      itemWidth: 10,
      itemHeight: 2,
      itemGap: 8
    },
    xAxis: {
      type: 'category',
      data: magLabels,
      axisLine: { lineStyle: { color: '#1E3A5F' } },
      axisTick: { show: false },
      axisLabel: { color: '#4A5C7A', fontSize: 9 }
    },
    yAxis: {
      min: 0,
      max: 1.05,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        color: '#4A5C7A', fontSize: 9,
        formatter: (v) => Math.round(v * 100) + '%'
      },
      splitLine: { lineStyle: { color: '#1E3A5F' } }
    },
    series: [
      {
        name: '医疗', type: 'line', smooth: true,
        data: chartData.map(d => d.medical),
        lineStyle: { color: '#F87171', width: 2 },
        itemStyle: { color: '#F87171' },
        symbol: 'circle', symbolSize: 5,
        markLine: {
          symbol: 'none', silent: true,
          label: { show: false },
          data: [
            { yAxis: thCollapse.medical, lineStyle: { color: '#F87171', type: 'dashed', width: 1, opacity: 0.6 } },
          ]
        }
      },
      {
        name: '救援', type: 'line', smooth: true,
        data: chartData.map(d => d.rescue),
        lineStyle: { color: '#FB923C', width: 2 },
        itemStyle: { color: '#FB923C' },
        symbol: 'circle', symbolSize: 5,
        markLine: {
          symbol: 'none', silent: true,
          label: { show: false },
          data: [{ yAxis: thCollapse.rescue, lineStyle: { color: '#FB923C', type: 'dashed', width: 1, opacity: 0.4 } }]
        }
      },
      {
        name: '交通', type: 'line', smooth: true,
        data: chartData.map(d => d.transport),
        lineStyle: { color: '#FBBF24', width: 2 },
        itemStyle: { color: '#FBBF24' },
        symbol: 'circle', symbolSize: 5,
        markLine: {
          symbol: 'none', silent: true,
          label: { show: false },
          data: [{ yAxis: thCollapse.transport, lineStyle: { color: '#FBBF24', type: 'dashed', width: 1, opacity: 0.4 } }]
        }
      },
      {
        name: '避难', type: 'line', smooth: true,
        data: chartData.map(d => d.shelter),
        lineStyle: { color: '#34D399', width: 2 },
        itemStyle: { color: '#34D399' },
        symbol: 'circle', symbolSize: 5,
        markLine: {
          symbol: 'none', silent: true,
          label: { show: false },
          data: [{ yAxis: thCollapse.shelter, lineStyle: { color: '#34D399', type: 'dashed', width: 1, opacity: 0.4 } }]
        }
      }
    ]
  })
}

// 监听 cascade 数据变化，更新图表
watch([cascade, allCascade], () => {
  nextTick(() => updateChart())
}, { deep: true })

// ==================== 时间步进推演 ====================
const timeEvolution = computed(() => data.time_evolution || null)
const timeSteps = computed(() => timeEvolution.value?.steps || [])
const currentStepIdx = ref(0)
const currentStep = computed(() => timeSteps.value[currentStepIdx.value] || null)

// 当前时间步的4系统状态
const currentStepSystems = computed(() => {
  const step = currentStep.value
  if (!step?.systems) return []
  return NODE_KEYS.map(key => {
    const sys = step.systems[key]
    if (!sys) return null
    return {
      key,
      name: sys.name,
      ratio: sys.ratio,
      collapsed: sys.collapsed,
      status: sys.status,
      color: sys.color,
      threshold: sys.threshold,
      drop: sys.drop,
    }
  }).filter(Boolean)
})

// 播放控制：自动推进时间步
const isPlaying = ref(false)
let playTimer = null

function togglePlay() {
  isPlaying.value ? stopPlay() : startPlay()
}

function startPlay() {
  if (timeSteps.value.length === 0) return
  if (currentStepIdx.value >= timeSteps.value.length - 1) currentStepIdx.value = 0
  isPlaying.value = true
  playTimer = setInterval(() => {
    if (currentStepIdx.value < timeSteps.value.length - 1) {
      currentStepIdx.value++
    } else {
      stopPlay()
    }
  }, 1500)
}

function stopPlay() {
  isPlaying.value = false
  if (playTimer) {
    clearInterval(playTimer)
    playTimer = null
  }
}

function selectStep(idx) {
  currentStepIdx.value = idx
  stopPlay()
}

// 震级切换时重置步进
watch(timeSteps, () => {
  currentStepIdx.value = 0
  stopPlay()
  nextTick(() => updateEvoChart())
})

// ==================== 时间推演 ECharts 折线图 ====================
const evoChartRef = ref(null)
let evoChartInstance = null
let evoResizeObserver = null

function initEvoChart() {
  if (!evoChartRef.value) return
  evoChartInstance = echarts.init(evoChartRef.value)
  updateEvoChart()
}

function updateEvoChart() {
  if (!evoChartInstance) return
  const steps = timeSteps.value
  if (steps.length === 0) {
    evoChartInstance.clear()
    return
  }

  const labels = steps.map(s => s.label)
  const seriesCfg = [
    { key: 'medical', name: '医疗', color: '#F87171' },
    { key: 'transport', name: '交通', color: '#FBBF24' },
    { key: 'rescue', name: '救援', color: '#FB923C' },
    { key: 'shelter', name: '避难', color: '#34D399' },
  ]

  evoChartInstance.setOption({
    grid: { left: 32, right: 14, top: 24, bottom: 20 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#142440',
      borderColor: '#1C2B43',
      borderWidth: 1,
      textStyle: { color: '#E6EDF7', fontSize: 10 },
      formatter(params) {
        const step = steps[params[0].dataIndex]
        let s = params[0].axisValue + ' · ' + (step?.desc || '') + '<br/>'
        params.forEach(p => {
          s += p.marker + p.seriesName + ': ' + (p.value * 100).toFixed(1) + '%<br/>'
        })
        return s
      }
    },
    legend: {
      top: 0, right: 0,
      textStyle: { color: '#7E91AC', fontSize: 9 },
      itemWidth: 10, itemHeight: 2, itemGap: 8
    },
    xAxis: {
      type: 'category',
      data: labels,
      axisLine: { lineStyle: { color: '#1E3A5F' } },
      axisTick: { show: false },
      axisLabel: { color: '#4A5C7A', fontSize: 9 }
    },
    yAxis: {
      min: 0, max: 1.05,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        color: '#4A5C7A', fontSize: 9,
        formatter: (v) => Math.round(v * 100) + '%'
      },
      splitLine: { lineStyle: { color: '#1E3A5F' } }
    },
    series: seriesCfg.map((cfg, idx) => {
      const sys = steps[0]?.systems?.[cfg.key]
      const markLineData = []
      if (sys) {
        markLineData.push({
          yAxis: sys.threshold,
          lineStyle: { color: cfg.color, type: 'dashed', width: 1, opacity: 0.4 }
        })
      }
      // 仅在第一条 series 上绘制当前时间步垂直标记线
      if (idx === 0) {
        markLineData.push({
          xAxis: currentStepIdx.value,
          lineStyle: { color: '#00D4FF', type: 'solid', width: 1.5, opacity: 0.8 },
          label: { show: false }
        })
      }
      return {
        name: cfg.name, type: 'line', smooth: true,
        data: steps.map(s => s.systems?.[cfg.key]?.ratio ?? 0),
        lineStyle: { color: cfg.color, width: 2 },
        itemStyle: { color: cfg.color },
        symbol: 'circle', symbolSize: 5,
        markLine: {
          symbol: 'none', silent: true,
          label: { show: false },
          data: markLineData
        }
      }
    })
  }, true)
}

// 当前步变化时刷新图表（移动垂直标记线）
watch(currentStepIdx, () => {
  updateEvoChart()
})

onMounted(async () => {
  await loadAllCascadeSummary()
  nextTick(() => {
    initChart()
    if (chartRef.value) {
      resizeObserver = new ResizeObserver(() => chartInstance?.resize())
      resizeObserver.observe(chartRef.value)
    }
    initEvoChart()
    if (evoChartRef.value) {
      evoResizeObserver = new ResizeObserver(() => evoChartInstance?.resize())
      evoResizeObserver.observe(evoChartRef.value)
    }
  })
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  chartInstance?.dispose()
  evoResizeObserver?.disconnect()
  evoChartInstance?.dispose()
  stopPlay()
})
</script>

<template>
  <div class="mode-root">
  <!-- Loading -->
  <div v-if="loading && !cascade" class="loading-overlay">
    <Loader2 :size="24" class="spin" />
    <span style="margin-left:8px;font-size:12px;color:var(--av-muted-foreground);">加载级联数据...</span>
  </div>

  <template v-else>
  <!-- ========== KPI Bar ========== -->
  <div class="kpi-bar">
    <div v-for="(item, i) in kpiItems" :key="i" class="kpi-cell">
      <div class="kpi-label">{{ item.label }}</div>
      <div class="kpi-value" :class="item.color">{{ item.value }}</div>
    </div>
  </div>

  <!-- ========== Three Columns ========== -->
  <div class="three-col">

    <!-- === Left Panel === -->
    <div class="col-panel">
      <!-- 状态横幅 -->
      <div class="status-banner" :style="{ borderColor: statusBanner.borderColor }">
        <div class="status-banner-icon" :style="{ background: statusBanner.bg }">
          <Zap :size="16" :style="{ color: statusBanner.color }" />
        </div>
        <div class="status-banner-text">
          <div class="status-banner-title">{{ statusBanner.title }}</div>
          <div class="status-banner-desc">{{ statusBanner.desc }}</div>
        </div>
      </div>

      <!-- 4x4 依赖矩阵 -->
      <!-- 传播强度条 -->
      <div class="section-label">传播强度</div>
      <div v-for="s in propStrengths" :key="s.label" style="margin-bottom:4px;">
        <div class="data-row">
          <span class="data-row-key">{{ s.label }}</span>
          <span class="data-row-val" style="color: var(--av-primary);">{{ s.pct }}%</span>
        </div>
        <div class="bar-mini">
          <div class="bar-mini-fill" :style="{ width: s.pct + '%', background: 'var(--av-primary)' }"></div>
        </div>
      </div>

      <!-- 级联时间线 -->
      <div class="section-label">级联时间线</div>
      <div v-for="t in (cascade?.cascade_timeline || [])" :key="t.step" class="timeline-item">
        <div class="timeline-dot" :style="{ background: nodes[t.system]?.color || '#7E91AC' }"></div>
        <div class="timeline-content">
          <div class="timeline-event">{{ t.event }}</div>
          <div class="timeline-desc">{{ t.description }}</div>
        </div>
        <div class="timeline-ratio" :style="{ color: nodes[t.system]?.color || '#7E91AC' }">
          {{ ((t.ratio || 0) * 100).toFixed(1) }}%
        </div>
      </div>
    </div>

    <!-- === Center Column === -->
    <div class="col-center">
      <!-- 网络图 -->
      <div class="map-container">
        <div class="map-toolbar">
          <div class="map-info">
            <GitBranch :size="12" style="vertical-align:middle;" /> 级联传播网络图 · M{{ currentMag.toFixed(1) }}
          </div>
          <div class="map-tools">
            <div class="map-tool active" title="依赖网络"><Share2 :size="14" /></div>
            <div class="map-tool active" title="传播路径"><Route :size="14" /></div>
            <div class="map-tool" title="重置选择" @click="clearSelection"><X :size="14" /></div>
          </div>
        </div>

        <svg class="network-graph" viewBox="0 0 500 320" preserveAspectRatio="xMidYMid meet"
             style="position:absolute;top:0;left:0;">
          <defs>
            <marker id="ah-muted" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6"
                    orient="auto" markerUnits="userSpaceOnUse">
              <path d="M0,0 L10,5 L0,10 Z" fill="#3a4a66" />
            </marker>
            <marker id="ah-red" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6"
                    orient="auto" markerUnits="userSpaceOnUse">
              <path d="M0,0 L10,5 L0,10 Z" fill="#F87171" />
            </marker>
            <marker id="ah-hi" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6"
                    orient="auto" markerUnits="userSpaceOnUse">
              <path d="M0,0 L10,5 L0,10 Z" fill="#00D4FF" />
            </marker>
          </defs>

          <!-- 依赖边 -->
          <line v-for="(edge, i) in depEdges" :key="'dep-' + i"
                class="dep-line"
                :class="{ dim: isEdgeDim(edge), hi: isEdgeHi(edge) }"
                :x1="edge.sx.toFixed(1)" :y1="edge.sy.toFixed(1)"
                :x2="edge.ex.toFixed(1)" :y2="edge.ey.toFixed(1)"
                :stroke="isEdgeHi(edge) ? '#00D4FF' : '#3a4a66'"
                :stroke-width="edge.width"
                :marker-end="isEdgeHi(edge) ? 'url(#ah-hi)' : 'url(#ah-muted)'" />

          <!-- 传播路径（红色虚线动画） -->
          <line v-for="(seg, i) in propSegments" :key="'prop-' + i"
                class="prop-path"
                :x1="seg.sx.toFixed(1)" :y1="seg.sy.toFixed(1)"
                :x2="seg.ex.toFixed(1)" :y2="seg.ey.toFixed(1)"
                stroke="#F87171" stroke-width="2.5"
                marker-end="url(#ah-red)" />

          <!-- 系统节点 -->
          <g v-for="sys in NODE_KEYS" :key="'node-' + sys"
             :class="['node-group', { selected: selectedNode === sys }]"
             @click="toggleNode(sys)">
            <!-- 崩溃节点脉冲圈 -->
            <circle v-if="nodes[sys]?.collapsed"
                    class="pulse-ring"
                    :cx="NODE_POSITIONS[sys].x" :cy="NODE_POSITIONS[sys].y" :r="30"
                    fill="none" :stroke="nodes[sys]?.color" stroke-width="2" />
            <!-- 节点圆 -->
            <circle class="node-circle"
                    :cx="NODE_POSITIONS[sys].x" :cy="NODE_POSITIONS[sys].y" :r="30"
                    fill="#0F1A2B" :stroke="nodes[sys]?.color || '#7E91AC'" stroke-width="2.5" />
            <!-- 系统名 -->
            <text :x="NODE_POSITIONS[sys].x" :y="NODE_POSITIONS[sys].y - 3"
                  text-anchor="middle" :fill="nodes[sys]?.color || '#7E91AC'"
                  font-size="11" font-weight="700">{{ nodes[sys]?.name || sys }}</text>
            <!-- 功能率 -->
            <text class="mono-txt" :x="NODE_POSITIONS[sys].x" :y="NODE_POSITIONS[sys].y + 10"
                  text-anchor="middle" :fill="nodes[sys]?.color || '#7E91AC'"
                  font-size="9" font-weight="600">{{ nodes[sys] ? nodes[sys].value.toFixed(1) + '%' : '—' }}</text>
            <!-- 状态标签 -->
            <text :x="statusPos(sys).x" :y="statusPos(sys).y"
                  text-anchor="middle" :fill="nodes[sys]?.color || '#7E91AC'"
                  font-size="8" font-weight="600">{{ nodes[sys]?.status || '—' }}</text>
          </g>
        </svg>

        <!-- 图例 -->
        <div class="map-legend">
          <div><span class="legend-dot" style="background:#F87171;"></span>已崩溃</div>
          <div><span class="legend-dot" style="background:#FB923C;"></span>级联风险</div>
          <div><span class="legend-dot" style="background:#3a4a66;"></span>依赖关系</div>
          <div><span class="legend-dot" style="background:#00D4FF;"></span>选中路径</div>
        </div>
        <div class="map-hint">点击节点高亮依赖路径</div>
      </div>

      <!-- 底部双图表 -->
      <div class="bottom-panels">
        <!-- 系统功能率变化（ECharts 折线图） -->
        <div class="chart-panel">
          <div class="chart-panel-title">
            <span>系统功能率变化 · 6震级（级联）</span>
            <span style="color:var(--state-error);font-size:9px;">--- 崩溃阈值</span>
          </div>
          <div class="chart-body">
            <div ref="chartRef" style="width:100%;height:100%;"></div>
          </div>
        </div>

        <!-- 4x4 依赖强度矩阵（SVG 热力图） -->
        <div class="chart-panel">
          <div class="chart-panel-title">
            <span>4x4 依赖强度矩阵</span>
            <span style="color:var(--av-muted-foreground);font-size:9px;">行→列</span>
          </div>
          <div class="chart-body" style="display:flex;align-items:center;justify-content:center;">
            <svg viewBox="0 0 184 168" style="width:100%;height:100%;max-height:140px;">
              <!-- 列标签 -->
              <text v-for="(l, j) in SYSTEM_LABELS" :key="'hl-' + j"
                    :x="HM_OX + j * HM_CELL + HM_CELL / 2" :y="HM_OY - 8"
                    text-anchor="middle" fill="#7E91AC" font-size="9">{{ l }}</text>
              <!-- 行标签 -->
              <text v-for="(l, i) in SYSTEM_LABELS" :key="'vl-' + i"
                    :x="HM_OX - 6" :y="HM_OY + i * HM_CELL + HM_CELL / 2 + 3"
                    text-anchor="end" fill="#7E91AC" font-size="9">{{ l }}</text>
              <!-- 单元格 -->
              <template v-for="(row, i) in depMatrix" :key="'hmr-' + i">
                <g v-for="(w, j) in row" :key="'hmc-' + i + '-' + j">
                  <rect class="heatmap-cell"
                        :x="HM_OX + j * HM_CELL + 1" :y="HM_OY + i * HM_CELL + 1"
                        :width="HM_CELL - 2" :height="HM_CELL - 2" rx="2"
                        :fill="depCellColor(w)">
                    <title>{{ SYSTEM_LABELS[i] }}→{{ SYSTEM_LABELS[j] }}: {{ w.toFixed(2) }}</title>
                  </rect>
                  <text class="mono-txt"
                        :x="HM_OX + j * HM_CELL + HM_CELL / 2"
                        :y="HM_OY + i * HM_CELL + HM_CELL / 2 + 3"
                        text-anchor="middle" :fill="depCellTxtColor(i, j, w)"
                        font-size="8" font-weight="600">{{ w.toFixed(2) }}</text>
                </g>
              </template>
            </svg>
          </div>
        </div>
      </div>
    </div>

    <!-- === Right Panel === -->
    <div class="col-panel">
      <!-- 级联传播链 -->
      <div class="panel-item red">
        <div class="panel-label">级联传播链 · M{{ currentMag.toFixed(1) }}</div>
        <div class="cascade-chain">
          <template v-for="(node, i) in chainNodes" :key="'chain-' + i">
            <div class="chain-node">
              <div class="chain-pill"
                   :style="{ background: node.color + '22', color: node.color }">
                {{ node.name }}{{ node.state }}
              </div>
              <div style="font-size:8px;color:var(--av-muted-foreground);font-family:var(--av-font-mono);">
                {{ node.value }}%
              </div>
            </div>
            <div v-if="i < chainNodes.length - 1 && i < chainEdgeProbs.length" class="chain-arrow">
              &#8594;<span>{{ chainEdgeProbs[i] }}%</span>
            </div>
            <div v-else-if="i < chainNodes.length - 1" class="chain-arrow">
              &#8594;
            </div>
          </template>
        </div>
      </div>

      <!-- 关键脆弱节点 -->
      <div class="panel-item red">
        <div class="panel-label">关键脆弱节点</div>
        <div v-for="v in vulnNodes" :key="v.name" style="margin-bottom:2px;">
          <div class="data-row">
            <span class="data-row-key">{{ v.name }}</span>
            <span class="data-row-val" :style="{ color: v.color }">{{ v.val }}</span>
          </div>
          <div class="bar-mini">
            <div class="bar-mini-fill" :style="{ width: v.pct + '%', background: v.color }"></div>
          </div>
        </div>
      </div>

      <!-- 影响范围 -->
      <div class="panel-item">
        <div class="panel-label">影响范围</div>
        <div v-for="item in impactData" :key="item.key" class="data-row">
          <span class="data-row-key">{{ item.key }}</span>
          <span class="data-row-val" :style="{ color: item.color }">{{ item.val }}</span>
        </div>
      </div>
    </div>

  </div>

  <!-- ========== 时间步进推演面板（全宽） ========== -->
  <div v-if="timeSteps.length" class="evo-panel">
    <!-- 标题栏 + 播放控制 -->
    <div class="evo-header">
      <div class="evo-title">
        <Clock :size="13" /> 时间步进推演 · 系统功能率随时间衰减
      </div>
      <div class="evo-controls">
        <span class="evo-step-info">
          {{ currentStep?.label }} · {{ currentStep?.desc }}
          <span class="evo-step-cf">级联因子 {{ (currentStep?.cascade_factor ?? 0).toFixed(2) }}</span>
        </span>
        <button class="evo-play-btn" :class="{ playing: isPlaying }" @click="togglePlay">
          <Pause v-if="isPlaying" :size="11" />
          <Play v-else :size="11" />
          <span>{{ isPlaying ? '暂停' : '播放' }}</span>
        </button>
      </div>
    </div>

    <!-- 时间节点轴 -->
    <div class="evo-timeline">
      <div class="evo-timeline-track">
        <div v-for="(step, i) in timeSteps" :key="i"
             class="evo-node"
             :class="{ active: i === currentStepIdx, passed: i < currentStepIdx }"
             @click="selectStep(i)">
          <div class="evo-node-dot"></div>
          <div class="evo-node-label">{{ step.label }}</div>
          <div class="evo-node-desc">{{ step.desc }}</div>
          <div class="evo-node-meta">崩 {{ step.collapsed_count }}/{{ NODE_KEYS.length }}</div>
        </div>
      </div>
    </div>

    <!-- 图表 + 状态卡片 -->
    <div class="evo-body">
      <div class="evo-chart-wrap">
        <div ref="evoChartRef" style="width:100%;height:100%;"></div>
      </div>
      <div class="evo-cards">
        <div v-for="sys in currentStepSystems" :key="sys.key"
             class="evo-card" :class="{ collapsed: sys.collapsed }"
             :style="{ '--sys-color': sys.color }">
          <div class="evo-card-head">
            <span class="evo-card-name">{{ sys.name }}</span>
            <span class="evo-card-status" :style="{ color: sys.color }">{{ sys.status }}</span>
          </div>
          <div class="evo-card-ratio" :style="{ color: sys.color }">
            {{ (sys.ratio * 100).toFixed(1) }}<span class="evo-card-unit">%</span>
          </div>
          <div class="evo-card-bar">
            <div class="evo-card-bar-fill" :style="{ width: (sys.ratio * 100) + '%', background: sys.color }"></div>
            <div class="evo-card-bar-threshold" :style="{ left: (sys.threshold * 100) + '%' }"></div>
          </div>
          <div class="evo-card-meta">
            <span>阈值{{ (sys.threshold * 100).toFixed(0) }}%</span>
            <span>Δ-{{ (sys.drop * 100).toFixed(1) }}%</span>
          </div>
        </div>
      </div>
    </div>
  </div>
  </template>
  </div>
</template>
