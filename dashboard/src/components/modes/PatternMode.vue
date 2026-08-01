<script setup>
import PageIntro from '../shell/PageIntro.vue'
import { ref, reactive, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import echarts from '../../engine/echartsSetup.js'
import {
  ShieldCheck,
  CheckSquare,
  Square,
  ZoomIn,
  ZoomOut,
  Home,
  MousePointerClick,
  Ruler,
  Maximize,
  Loader2
} from 'lucide-vue-next'
import { useDashboardData } from '../../composables/useDashboardData.js'
import { useMagnitude } from '../../composables/useMagnitude.js'
import MapContainer from '../map/MapContainer.vue'

const { data, loading, error } = useDashboardData()
const { currentMag } = useMagnitude()

/* ============================================================
   KPI Bar 数据 (来自 JSON)
   ============================================================ */
const kpiItems = computed(() => {
  const k = data.kpi
  if (!k) return []
  return [
    { label: '医疗机构', value: `${k.total_hospitals}家`, color: 'accent' },
    { label: '总人口', value: `${(k.total_population / 10000).toFixed(1)}万`, color: 'accent' },
    { label: 'GDP总量', value: `¥${k.total_gdp_yi.toFixed(0)}亿`, color: 'accent' },
    { label: '路网阻断率', value: `${(k.road_block_rate * 100).toFixed(1)}%`, color: 'red' }
  ]
})

/* ============================================================
   区县数据 (合并 district_loss + spatial_mismatch)
   ============================================================ */
const districts = computed(() => {
  const dl = data.charts?.district_loss
  const sm = data.charts?.spatial_mismatch
  if (!dl || !sm) return []

  // 用 spatial_mismatch 建立 GDP 查找表
  const gdpMap = {}
  for (const s of sm) {
    gdpMap[s.district] = s.gdp
  }

  return dl.map(d => {
    const gdp = gdpMap[d.district] || 0
    const popW = d.population / 10000
    // 依据人口密度判定密度等级
    let density = '低', densityPct = 10
    if (popW > 90) { density = '高'; densityPct = 100 }
    else if (popW > 75) { density = '中高'; densityPct = 65 }
    else if (popW > 60) { density = '中'; densityPct = 45 }

    return {
      name: d.district,
      pop: popW,
      gdp: gdp,
      grids: 0, // JSON 无此字段，保持 0
      hospitals: 0, // JSON 无分区医院数
      loss: d.loss,
      intensity: d.intensity,
      exposed: d.exposed,
      density,
      densityPct
    }
  })
})

function getDensityColor(level) {
  switch (level) {
    case '高':   return 'var(--state-error)'
    case '中高': return 'var(--state-orange)'
    case '中':   return 'var(--state-warning)'
    default:     return 'var(--state-success)'
  }
}

/* ============================================================
   设施分布数据 (来自 accessibility_distribution)
   ============================================================ */
const facilities = computed(() => {
  const ad = data.charts?.accessibility_distribution
  if (!ad) return []
  const result = []
  // 医疗机构
  const h = ad.hospitals
  if (h) {
    const total = (h['正常可达'] || 0) + (h['可达但受限'] || 0) + (h['不可达'] || 0)
    result.push({ label: '医疗机构', value: `${total}家`, pct: 100, color: 'var(--state-success)' })
  }
  // 其他设施
  if (ad.facilities) {
    for (const [name, dist] of Object.entries(ad.facilities)) {
      const total = (dist['正常可达'] || 0) + (dist['可达但受限'] || 0) + (dist['不可达'] || 0)
      const okPct = total > 0 ? Math.round((dist['正常可达'] || 0) / total * 100) : 0
      let color = 'var(--state-success)'
      if (okPct < 30) color = 'var(--state-error)'
      else if (okPct < 60) color = 'var(--state-orange)'
      result.push({ label: name, value: `${total}处`, pct: okPct, color })
    }
  }
  return result
})

/* ============================================================
   图层切换状态
   ============================================================ */
const layers = reactive({
  density: true,
  hospital: true,
  road: false,
  fault: true,
  nightlight: false
})

const mapLayers = computed(() => ({
  districts: true,
  roads: layers.road,
  blockedRoads: false,
  hospitals: layers.hospital,
  rescue: true,
  shelters: true,
  hazards: true,
  fault: layers.fault,
  intensity: false,
  epicenter: false,
}))

const layerItems = [
  { key: 'hospital',  label: '医院分布' },
  { key: 'road',      label: '路网健康' },
  { key: 'fault',    label: '断裂带' }
]

function toggleLayer(key) {
  layers[key] = !layers[key]
}

/* ============================================================
   区县选中状态 & 地图高亮
   ============================================================ */
const selectedDistrict = ref('')

function selectDistrict(name) {
  selectedDistrict.value = selectedDistrict.value === name ? '' : name
}

/* ============================================================
   SVG 地图数据
   ============================================================ */
// 9 区县多边形路径 (坐标来自模板)
const districtPaths = [
  { name: '长丰县', d: 'M150,20 Q220,15 290,25 Q310,50 295,75 Q230,80 170,70 Q140,50 150,20Z', fill: 'rgba(52,211,153,0.06)', stroke: '#1E3A5F', textX: 220, textY: 48, textColor: '#4A5C7A' },
  { name: '肥东县', d: 'M295,75 Q360,70 410,90 Q420,130 400,170 Q350,175 300,160 Q285,120 295,75Z', fill: 'rgba(52,211,153,0.05)', stroke: '#1E3A5F', textX: 350, textY: 120, textColor: '#4A5C7A' },
  { name: '巢湖市', d: 'M380,180 Q440,175 465,210 Q470,250 440,265 Q390,260 370,230 Q365,200 380,180Z', fill: 'rgba(52,211,153,0.04)', stroke: '#1E3A5F', textX: 415, textY: 225, textColor: '#4A5C7A' },
  { name: '庐江县', d: 'M230,230 Q290,225 340,245 Q345,270 310,275 Q250,272 215,260 Q210,240 230,230Z', fill: 'rgba(52,211,153,0.03)', stroke: '#1E3A5F', textX: 275, textY: 258, textColor: '#4A5C7A' },
  { name: '肥西县', d: 'M80,150 Q140,145 175,165 Q180,210 150,240 Q100,245 65,220 Q55,180 80,150Z', fill: 'rgba(52,211,153,0.06)', stroke: '#1E3A5F', textX: 115, textY: 200, textColor: '#4A5C7A' },
  { name: '蜀山区', d: 'M110,80 Q160,75 175,100 Q180,130 160,150 Q120,155 95,135 Q85,105 110,80Z', fill: 'rgba(251,191,36,0.10)', stroke: '#1E3A5F', textX: 132, textY: 115, textColor: '#4A5C7A' },
  { name: '庐阳区', d: 'M170,70 Q220,65 240,85 Q245,110 225,130 Q190,135 170,115 Q160,90 170,70Z', fill: 'rgba(248,113,113,0.18)', stroke: '#F87171', textX: 200, textY: 100, textColor: '#F87171', bold: true },
  { name: '瑶海区', d: 'M240,85 Q285,80 300,100 Q305,125 285,145 Q250,150 235,125 Q230,100 240,85Z', fill: 'rgba(248,113,113,0.16)', stroke: '#F87171', textX: 265, textY: 112, textColor: '#F87171', bold: true },
  { name: '包河区', d: 'M175,130 Q230,125 260,145 Q270,175 245,195 Q200,200 170,180 Q155,155 175,130Z', fill: 'rgba(251,146,60,0.13)', stroke: '#1E3A5F', textX: 210, textY: 162, textColor: '#4A5C7A' }
]

// 道路网络 (主干道 stroke=#3A5278)
const majorRoads = [
  [65, 48, 295, 48, 0.7], [95, 100, 300, 100, 0.7], [65, 140, 410, 140, 0.7],
  [65, 200, 465, 200, 0.6], [215, 255, 340, 255, 0.6],
  [130, 25, 130, 240, 0.7], [210, 25, 210, 200, 0.7], [265, 25, 265, 160, 0.7],
  [350, 75, 350, 265, 0.6], [95, 80, 95, 220, 0.5]
]

// 次干道 (stroke=#2E4468)
const secondaryRoads = [
  [175, 70, 175, 240, 0.4], [240, 85, 240, 195, 0.4], [295, 75, 295, 175, 0.4],
  [160, 80, 160, 150, 0.4], [115, 150, 175, 165, 0.4], [150, 240, 310, 245, 0.4],
  [200, 130, 200, 200, 0.4], [245, 100, 245, 195, 0.4], [115, 200, 150, 240, 0.4],
  [380, 180, 410, 170, 0.4], [340, 245, 370, 230, 0.4]
]

// 关键瓶颈路段 (stroke=#FB923C)
const keyRoads = [
  [175, 95, 210, 100, 1.3, 0.8],
  [225, 115, 245, 125, 1.3, 0.8],
  [200, 140, 230, 175, 1.3, 0.7],
  [265, 125, 285, 130, 1.3, 0.8],
  [155, 140, 175, 160, 1.3, 0.7],
  [340, 140, 370, 145, 1.3, 0.6]
]

// 医院 POI 坐标
const hospitalPois = [
  [190, 90], [198, 95], [195, 105], [205, 92], [210, 100],
  [215, 108], [200, 115], [220, 105], [225, 115], [185, 105],
  [190, 118], [215, 120], [250, 100], [260, 108], [268, 115],
  [255, 120], [270, 125], [245, 115], [275, 105], [282, 115],
  [120, 100], [130, 105], [125, 115], [115, 120], [140, 110],
  [135, 125], [195, 150], [210, 155], [220, 165], [200, 170],
  [230, 175], [320, 100], [350, 110], [340, 130], [370, 120],
  [380, 145], [240, 45], [260, 55], [100, 170], [120, 190], [90, 200]
]

/* ============================================================
   地图 Tooltip
   ============================================================ */
const mapContainerRef = ref(null)
const tooltip = reactive({ show: false, x: 0, y: 0, district: null })

function showDistrictTooltip(event, name) {
  const d = districts.value.find(x => x.name === name)
  if (!d) return
  const rect = mapContainerRef.value.getBoundingClientRect()
  tooltip.x = event.clientX - rect.left + 15
  tooltip.y = event.clientY - rect.top + 15
  tooltip.district = d
  tooltip.show = true
}

function moveDistrictTooltip(event) {
  if (!tooltip.show) return
  const rect = mapContainerRef.value.getBoundingClientRect()
  tooltip.x = event.clientX - rect.left + 15
  tooltip.y = event.clientY - rect.top + 15
}

function hideDistrictTooltip() {
  tooltip.show = false
}

/* ============================================================
   底线债务指数仪表 (SVG arc + needle)
   ============================================================ */
const debtValue = computed(() => data.charts?.resilience?.resilience_index || 0.587)
// 债务等级文案：与 debtValue 数值区间保持一致（高韧性→轻度债务，避免同屏数值与文案冲突）
const debtLevel = computed(() => {
  const v = debtValue.value
  if (v >= 0.65) return { text: '轻度债务', color: 'var(--state-success)' }
  if (v >= 0.5) return { text: '中度债务', color: 'var(--state-warning)' }
  return { text: '重度债务', color: 'var(--state-error)' }
})
const debtGauge = computed(() => {
  const cx = 24, cy = 26, len = 14, r2 = 20
  const angle = (debtValue.value - 0.5) * Math.PI
  const needleX = cx + Math.sin(angle) * len
  const needleY = cy - Math.cos(angle) * len

  const startAngle = Math.PI
  const endAngle = startAngle + debtValue.value * Math.PI
  const x1 = cx + r2 * Math.cos(startAngle)
  const y1 = cy + r2 * Math.sin(startAngle)
  const xe = cx + r2 * Math.cos(endAngle)
  const ye = cy + r2 * Math.sin(endAngle)
  const arcPath = `M${x1},${y1} A${r2},${r2} 0 0,1 ${xe},${ye}`

  return { needleX, needleY, arcPath, cx, cy }
})

/* ============================================================
   老城风险 - 瓶颈路段表
   ============================================================ */
const bottleneckRoads = [
  { id: '#25821', length: '315m', status: '老', color: 'var(--state-error)' },
  { id: '#25675', length: '370m', status: '老', color: 'var(--state-error)' },
  { id: '#33397', length: '315m', status: '老', color: 'var(--state-error)' },
  { id: '#37114', length: '2.4km', status: '断', color: 'var(--state-orange)' },
  { id: '#53086', length: '1.9km', status: '断', color: 'var(--state-orange)' }
]

/* ============================================================
   ECharts 图表
   ============================================================ */
const barChartRef = ref(null)
const radarChartRef = ref(null)
let barChart = null
let radarChart = null

function createBarOption() {
  return {
    grid: { left: 50, right: 45, top: 28, bottom: 22 },
    legend: {
      data: ['人口(万)', 'GDP(亿)'],
      textStyle: { color: '#7E91AC', fontSize: 9 },
      itemWidth: 10, itemHeight: 4,
      top: 0, right: 0
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#142440',
      borderColor: '#1C2B43',
      borderWidth: 1,
      textStyle: { color: '#E6EDF7', fontSize: 10 },
      axisPointer: { type: 'shadow' }
    },
    xAxis: [
      {
        type: 'value',
        name: '万',
        nameTextStyle: { color: '#00D4FF', fontSize: 8 },
        position: 'bottom',
        axisLabel: { color: '#4A5C7A', fontSize: 8 },
        splitLine: { lineStyle: { color: '#1E3A5F' } },
        axisLine: { lineStyle: { color: '#1E3A5F' } }
      },
      {
        type: 'value',
        name: '亿',
        nameTextStyle: { color: '#A78BFA', fontSize: 8 },
        position: 'top',
        axisLabel: { color: '#4A5C7A', fontSize: 8 },
        splitLine: { show: false },
        axisLine: { lineStyle: { color: '#1E3A5F' } }
      }
    ],
    yAxis: {
      type: 'category',
      data: districts.value.map(d => d.name),
      axisLabel: { color: '#7E91AC', fontSize: 9 },
      axisLine: { lineStyle: { color: '#1E3A5F' } },
      axisTick: { show: false }
    },
    series: [
      {
        name: '人口(万)',
        type: 'bar',
        data: districts.value.map(d => d.pop),
        itemStyle: { color: 'rgba(0,212,255,0.6)', borderColor: '#00D4FF', borderWidth: 1, borderRadius: 2 },
        barWidth: 5
      },
      {
        name: 'GDP(亿)',
        type: 'bar',
        xAxisIndex: 1,
        data: districts.value.map(d => d.gdp),
        itemStyle: { color: 'rgba(167,139,250,0.5)', borderColor: '#A78BFA', borderWidth: 1, borderRadius: 2 },
        barWidth: 5
      }
    ]
  }
}

// 柱状图：初始化后每次数据变化通过 setBarChart() 刷新（首次 init 时也调用）
function initBarChart() {
  if (!barChartRef.value) return
  if (!barChart) barChart = echarts.init(barChartRef.value)
  setBarChart()
}
function setBarChart() {
  if (!barChart) return
  barChart.setOption(createBarOption())
}

// 4系统基线功能率：从 JSON 的 charts.collapse 读取（shelter 为容量比可能>1，clamp 到1）
const radarCoverage = computed(() => {
  const col = data.charts?.collapse
  if (!col) return [0, 0, 0, 0]
  const clamp = v => (v == null ? 0 : Math.min(Math.max(v, 0), 1))
  return [clamp(col.medical_ratio), clamp(col.rescue_ratio), clamp(col.transport_ratio), clamp(col.shelter_ratio)]
})

// 雷达综合覆盖率（4项均值，用于雷达图标题，动态化替代硬编码 0.705）
const radarAvg = computed(() => {
  const v = radarCoverage.value
  const sum = v[0] + v[1] + v[2] + v[3]
  return (sum / 4).toFixed(3)
})

function createRadarOption() {
  return {
    tooltip: {
      backgroundColor: '#142440',
      borderColor: '#1C2B43',
      borderWidth: 1,
      textStyle: { color: '#E6EDF7', fontSize: 10 },
      formatter: (params) => {
        const labels = ['医疗', '救援', '交通', '避难']
        return labels.map((l, i) => `${l}: ${(params.value[i] * 100).toFixed(0)}%`).join('<br/>')
      }
    },
    radar: {
      indicator: [
        { name: '医疗', max: 1 },
        { name: '救援', max: 1 },
        { name: '交通', max: 1 },
        { name: '避难', max: 1 }
      ],
      center: ['50%', '55%'],
      radius: '60%',
      min: 0,
      max: 1,
      splitNumber: 4,
      axisName: { color: '#7E91AC', fontSize: 11, fontWeight: 600 },
      splitLine: { lineStyle: { color: '#1E3A5F' } },
      splitArea: { show: false },
      axisLine: { lineStyle: { color: '#1E3A5F' } }
    },
    series: [{
      type: 'radar',
      data: [{
        value: radarCoverage.value,
        name: '基线覆盖率',
        areaStyle: { color: 'rgba(0,212,255,0.15)' },
        lineStyle: { color: '#00D4FF', width: 2 },
        symbol: 'circle',
        symbolSize: 6,
        itemStyle: { color: '#00D4FF' }
      }]
    }]
  }
}

function initRadarChart() {
  if (!radarChartRef.value) return
  if (!radarChart) radarChart = echarts.init(radarChartRef.value)
  setRadarChart()
}
function setRadarChart() {
  if (!radarChart) return
  radarChart.setOption(createRadarOption())
}

function handleResize() {
  barChart?.resize()
  radarChart?.resize()
}

/* ============================================================
   生命周期
   ============================================================ */
// 数据变化时刷新图表（首次初始化，之后每次震级切换/数据更新都重新 setOption）
watch(() => [data.kpi, data.charts], async () => {
  if (!data.kpi) return
  await nextTick()
  if (barChartRef.value) initBarChart()
  if (radarChartRef.value) initRadarChart()
  // 已 init 的实例也会被 initBarChart/initRadarChart 内的 setBarChart/setRadarChart 刷新
}, { immediate: true })

onMounted(() => {
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  barChart?.dispose()
  radarChart?.dispose()
})
</script>

<template>
  <div class="mode-root">
    <PageIntro question="合肥的生命线系统空间上怎么分布？风险与资源是否错配？" :points="['区县风险排名', '空间错配', '关键设施分布']" />
  <!-- ========== Loading ========== -->
  <div v-if="loading && !data.kpi" class="loading-overlay">
    <Loader2 :size="24" class="spin" />
    <span style="margin-left:8px;font-size:12px;color:var(--av-muted-foreground);">加载格局数据...</span>
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
      <!-- Status Banner -->
      <div class="status-banner" style="border-color:rgba(52,211,153,0.3);">
        <div class="status-banner-icon" style="background:rgba(52,211,153,0.15);">
          <ShieldCheck class="w-4 h-4" style="color:var(--state-success);" />
        </div>
        <div class="status-banner-text">
          <div class="status-banner-title">城市基线状态</div>
          <div class="status-banner-desc">未触发地震 · 显示固有空间债务</div>
        </div>
      </div>

      <!-- 9 Districts List -->
      <div class="section-label">9区县基线</div>
      <div>
        <div
          v-for="d in districts"
          :key="d.name"
          class="dist-row"
          :class="{ highlight: selectedDistrict === d.name }"
          @click="selectDistrict(d.name)"
        >
          <div class="data-row">
            <span class="dist-name">{{ d.name }}</span>
            <span class="data-row-val" style="color:var(--av-primary);">{{ d.pop }}万</span>
          </div>
          <div style="font-size:9px;color:var(--av-muted-foreground);">
            ¥{{ d.gdp }}亿 · {{ d.grids }}格 · {{ d.hospitals }}院
          </div>
          <div class="bar-mini">
            <div class="bar-mini-fill" :style="{ width: d.densityPct + '%', background: getDensityColor(d.density) }"></div>
          </div>
        </div>
      </div>

      <!-- Facility Distribution -->
      <div class="section-label">设施分布</div>
      <div v-for="(f, i) in facilities" :key="i" class="facility-row">
        <span class="facility-label">{{ f.label }}</span>
        <div class="facility-bar-wrap">
          <div class="facility-bar-fill" :style="{ width: f.pct + '%', background: f.color }"></div>
        </div>
        <span class="facility-val" :style="{ color: f.color }">{{ f.value }}</span>
      </div>

      <!-- Layers -->
      <div class="section-label">图层</div>
      <div class="flex flex-col gap-1">
        <div
          v-for="layer in layerItems"
          :key="layer.key"
          class="flex items-center gap-2 text-xs cursor-pointer"
          style="padding:2px 4px;"
          :style="{ color: layers[layer.key] ? 'var(--av-foreground)' : 'var(--av-muted-foreground)' }"
          @click="toggleLayer(layer.key)"
        >
          <CheckSquare v-if="layers[layer.key]" class="w-3.5 h-3.5" style="color:var(--av-primary);" />
          <Square v-else class="w-3.5 h-3.5" />
          <span>{{ layer.label }}</span>
        </div>
      </div>
    </div>

    <!-- === Center: Map + Charts === -->
    <div class="col-center">
      <!-- SVG Map -->
      <div ref="mapContainerRef" class="map-container">
        <MapContainer
          :magnitude="currentMag"
          :layers="mapLayers"
          class="map-leaflet"
        />

        <!-- Map Toolbar -->
        <div class="map-toolbar">
          <div class="map-info">基线拓扑视图 · 悬停区县查看详情 · 点击左栏区县高亮地图</div>
        </div>

        <!-- Legend -->
        <div class="map-legend">
          <div style="display:flex;align-items:center;gap:4px;">
            <span style="color:var(--av-muted-foreground);">人口密度</span>
            <span style="display:inline-block;width:48px;height:5px;border-radius:1px;background:linear-gradient(to right,#34D399,#FBBF24,#FB923C,#F87171);"></span>
            <span style="color:#34D399;">低</span>
            <span style="color:#F87171;">高</span>
          </div>
          <div>
            <span style="color:#34D399;">●</span>医疗机构(426)
            <span style="color:#FB923C;">━</span>关键瓶颈路段
          </div>
          <div>
            <span style="color:#3A5278;">─</span>路网(58K)
            <span style="color:#A78BFA;">┄</span>郯庐断裂带
          </div>
        </div>

        <!-- District Tooltip -->
        <div
          v-show="tooltip.show"
          class="district-tooltip"
          :style="{ left: tooltip.x + 'px', top: tooltip.y + 'px' }"
        >
          <div v-if="tooltip.district" style="color:var(--av-primary);font-weight:600;margin-bottom:4px;">
            {{ tooltip.district.name }} · 人口密度{{ tooltip.district.density === '高' ? '极高' : tooltip.district.density === '中高' ? '较高' : tooltip.district.density === '中' ? '中等' : '低密度' }}
          </div>
          <div v-if="tooltip.district" style="border-top:1px solid var(--av-border);margin-bottom:4px;"></div>
          <template v-if="tooltip.district">
            <div style="display:flex;justify-content:space-between;color:var(--av-muted-foreground);">
              <span>总人口</span>
              <span style="color:var(--av-foreground);font-family:var(--av-font-mono);">{{ tooltip.district.pop }}万</span>
            </div>
            <div style="display:flex;justify-content:space-between;color:var(--av-muted-foreground);">
              <span>GDP</span>
              <span style="color:var(--av-foreground);font-family:var(--av-font-mono);">¥{{ tooltip.district.gdp }}亿</span>
            </div>
            <div style="display:flex;justify-content:space-between;color:var(--av-muted-foreground);">
              <span>空间网格</span>
              <span style="color:var(--av-foreground);font-family:var(--av-font-mono);">{{ tooltip.district.grids }}</span>
            </div>
            <div style="display:flex;justify-content:space-between;color:var(--av-muted-foreground);">
              <span>医院数</span>
              <span style="color:var(--state-success);font-family:var(--av-font-mono);">{{ tooltip.district.hospitals }}家</span>
            </div>
          </template>
        </div>
      </div>

      <!-- Bottom Panels -->
      <div class="bottom-panels">
        <!-- Bar Chart -->
        <div class="chart-panel">
          <div class="chart-panel-title">
            <span>9区县人口与GDP对比</span>
            <span style="color:var(--av-primary);font-size:10px;">基线数据</span>
          </div>
          <div ref="barChartRef" class="chart-body" style="width:100%;height:100%;"></div>
        </div>

        <!-- Radar Chart -->
        <div class="chart-panel">
          <div class="chart-panel-title">
            <span>4系统基线覆盖率</span>
            <span style="color:var(--state-warning);font-size:10px;">综合 {{ radarAvg }}</span>
          </div>
          <div ref="radarChartRef" class="chart-body" style="width:100%;height:100%;"></div>
        </div>
      </div>
    </div>

    <!-- === Right Panel === -->
    <div class="col-panel">
      <!-- 空间错配分析 -->
      <!-- 基线韧性 -->
      <div class="panel-item accent">
        <div class="panel-label">底线债务指数</div>
        <div class="flex items-center gap-2">
          <svg width="48" height="30" viewBox="0 0 48 30">
            <path d="M5,26 A20,20 0 0,1 43,26" fill="none" stroke="#1E3A5F" stroke-width="3" />
            <path :d="debtGauge.arcPath" fill="none" :stroke="debtLevel.color" stroke-width="3" stroke-linecap="round" />
            <line
              :x1="debtGauge.cx"
              :y1="debtGauge.cy"
              :x2="debtGauge.needleX"
              :y2="debtGauge.needleY"
              stroke="#FB923C"
              stroke-width="1.5"
              stroke-linecap="round"
            />
            <circle :cx="debtGauge.cx" :cy="debtGauge.cy" r="2" fill="#FB923C" />
          </svg>
          <div>
            <div style="font-size:18px;font-weight:700;font-family:var(--av-font-mono);" :style="{ color: debtLevel.color }">
              {{ debtValue }}
            </div>
            <div style="font-size:9px;" :style="{ color: debtLevel.color }">{{ debtLevel.text }}</div>
          </div>
        </div>
        <div class="bar-mini" style="margin-top:4px;">
          <div class="bar-mini-fill" :style="{ width: (debtValue * 100).toFixed(1) + '%', background: debtLevel.color }"></div>
        </div>
        <div style="display:flex;justify-content:space-between;font-size:8px;color:var(--av-muted-foreground);margin-top:2px;">
          <span>0.0 低</span><span>0.4</span><span>0.6</span><span>1.0 高</span>
        </div>
      </div>
    </div>

  </div>
  </template>
  </div>
</template>
