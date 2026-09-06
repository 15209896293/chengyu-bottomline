<script setup>
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import echarts from '../../engine/echartsSetup.js'
import { useMagnitude } from '../../composables/useMagnitude.js'
import { useDashboardData } from '../../composables/useDashboardData.js'
import {
  Zap, AlertOctagon, AlertTriangle, ShieldCheck,
  Play, Pause, RotateCcw,
  CheckSquare, Square,
  ZoomIn, ZoomOut, Home, MousePointerClick, Ruler, Maximize,
  Loader2
} from 'lucide-vue-next'
import MapContainer from '../map/MapContainer.vue'
import RealtimeProbe from './RealtimeProbe.vue'

// ==================== DATA ====================
const COLLAPSE_THRESHOLD = 0.30

// 暴露度缩放因子（相对M5.5）
const EXPOSURE_SCALE = [0.15, 1.0, 1.5, 2.0, 2.8, 3.5]

// 6震级系统功能率数据（从 JSON 异步加载）
const allMagData = ref([])

// 双档阈值对比数据
const dualThreshold = ref(null)

// 加载双档阈值对比数据
async function loadDualThreshold() {
  if (dualThreshold.value) return
  try {
    const resp = await fetch(import.meta.env.BASE_URL + 'data/dual_threshold_report.json')
    if (resp.ok) {
      dualThreshold.value = await resp.json()
    }
  } catch (e) {
    console.error('Failed to load dual threshold:', e)
  }
}

// 加载全部6震级的系统功能率数据（用于响应曲线和崩溃阈值表）
async function loadAllMagData() {
  if (allMagData.value.length > 0) return
  const summary = []
  for (const mag of magnitudes) {
    try {
      const resp = await fetch(`${import.meta.env.BASE_URL}data/dashboard_M${mag.toFixed(1)}.json`)
      if (resp.ok) {
        const json = await resp.json()
        summary.push({
          mag,
          medical: json.charts?.collapse?.medical_ratio ?? 0,
          rescue: json.charts?.collapse?.rescue_ratio ?? 0,
          transport: json.charts?.collapse?.transport_ratio ?? 0,
          shelter: json.charts?.collapse?.shelter_ratio ?? 0,
          resilience: json.charts?.resilience?.resilience_index ?? 0,
          medC: json.charts?.collapse?.medical_collapse ?? false,
          resC: json.charts?.collapse?.rescue_collapse ?? false,
          transC: json.charts?.collapse?.transport_collapse ?? false,
          shelC: json.charts?.collapse?.shelter_collapse ?? false,
          cityC: json.charts?.collapse?.city_collapse ?? false,
        })
      }
    } catch (e) {
      console.error(`Failed to load M${mag}:`, e)
    }
  }
  allMagData.value = summary
}

// SVG地图：9区县多边形
const districts = [
  { name: '长丰县', path: 'M150,20 Q220,15 290,25 Q310,50 295,75 Q230,80 170,70 Q140,50 150,20Z', fill: 'rgba(0, 255, 148,0.04)', stroke: '#1E3A5F', sw: 0.5, lx: 220, ly: 48, tc: '#5A6B82', fw: 400, il: 'I=5.2', ic: '#00FF94' },
  { name: '肥东县', path: 'M295,75 Q360,70 410,90 Q420,130 400,170 Q350,175 300,160 Q285,120 295,75Z', fill: 'rgba(255, 184, 0,0.04)', stroke: '#1E3A5F', sw: 0.5, lx: 350, ly: 120, tc: '#5A6B82', fw: 400, il: 'I=5.2', ic: '#FFB800' },
  { name: '巢湖市', path: 'M380,180 Q440,175 465,210 Q470,250 440,265 Q390,260 370,230 Q365,200 380,180Z', fill: 'rgba(0, 255, 148,0.02)', stroke: '#1E3A5F', sw: 0.5, lx: 415, ly: 225, tc: '#5A6B82', fw: 400, il: 'I=4.6', ic: '#00FF94' },
  { name: '庐江县', path: 'M230,230 Q290,225 340,245 Q345,270 310,275 Q250,272 215,260 Q210,240 230,230Z', fill: 'rgba(0, 255, 148,0.01)', stroke: '#1E3A5F', sw: 0.5, lx: 275, ly: 258, tc: '#5A6B82', fw: 400, il: 'I=4.3', ic: '#00FF94' },
  { name: '肥西县', path: 'M80,150 Q140,145 175,165 Q180,210 150,240 Q100,245 65,220 Q55,180 80,150Z', fill: 'rgba(0, 255, 148,0.03)', stroke: '#1E3A5F', sw: 0.5, lx: 115, ly: 200, tc: '#5A6B82', fw: 400, il: 'I=4.9', ic: '#00FF94' },
  { name: '蜀山区', path: 'M110,80 Q160,75 175,100 Q180,130 160,150 Q120,155 95,135 Q85,105 110,80Z', fill: 'rgba(255, 184, 0,0.06)', stroke: '#1E3A5F', sw: 0.5, lx: 132, ly: 115, tc: '#5A6B82', fw: 400, il: 'I=5.3', ic: '#FFB800' },
  { name: '庐阳区', path: 'M170,70 Q220,65 240,85 Q245,110 225,130 Q190,135 170,115 Q160,90 170,70Z', fill: 'rgba(255, 68, 68,0.08)', stroke: '#FF4444', sw: 0.6, lx: 200, ly: 100, tc: '#FF4444', fw: 600, il: 'I=6.0', ic: '#FF4444' },
  { name: '瑶海区', path: 'M240,85 Q285,80 300,100 Q305,125 285,145 Q250,150 235,125 Q230,100 240,85Z', fill: 'rgba(255, 68, 68,0.1)', stroke: '#FF4444', sw: 0.6, lx: 265, ly: 112, tc: '#FF4444', fw: 600, il: 'I=6.1', ic: '#FF4444' },
  { name: '包河区', path: 'M175,130 Q230,125 260,145 Q270,175 245,195 Q200,200 170,180 Q155,155 175,130Z', fill: 'rgba(255, 184, 0,0.06)', stroke: '#1E3A5F', sw: 0.5, lx: 210, ly: 162, tc: '#5A6B82', fw: 400, il: 'I=5.3', ic: '#FFB800' }
]

// 医院POI（x, y, baseReach 基础可达性）
const hospitals = [
  // 庐阳+瑶海（高烈度区）
  { x: 190, y: 90, br: 0.40 }, { x: 198, y: 95, br: 0.40 }, { x: 195, y: 105, br: 0.40 },
  { x: 205, y: 92, br: 0.35 }, { x: 210, y: 100, br: 0.30 }, { x: 215, y: 108, br: 0.30 },
  { x: 200, y: 115, br: 0.40 }, { x: 220, y: 105, br: 0.35 }, { x: 225, y: 115, br: 0.30 },
  { x: 185, y: 105, br: 0.40 }, { x: 190, y: 118, br: 0.40 }, { x: 215, y: 120, br: 0.35 },
  { x: 250, y: 100, br: 0.35 }, { x: 260, y: 108, br: 0.30 }, { x: 268, y: 115, br: 0.30 },
  { x: 255, y: 120, br: 0.35 }, { x: 270, y: 125, br: 0.30 }, { x: 245, y: 115, br: 0.35 },
  { x: 275, y: 105, br: 0.30 }, { x: 282, y: 115, br: 0.30 },
  // 蜀山区（中烈度）
  { x: 120, y: 100, br: 0.60 }, { x: 130, y: 105, br: 0.60 }, { x: 125, y: 115, br: 0.60 },
  { x: 115, y: 120, br: 0.65 }, { x: 140, y: 110, br: 0.60 }, { x: 135, y: 125, br: 0.60 },
  // 包河区
  { x: 195, y: 150, br: 0.60 }, { x: 210, y: 155, br: 0.55 }, { x: 220, y: 165, br: 0.55 },
  { x: 200, y: 170, br: 0.60 }, { x: 230, y: 175, br: 0.55 },
  // 远区（低烈度，可达）
  { x: 320, y: 100, br: 0.90 }, { x: 350, y: 110, br: 0.90 }, { x: 340, y: 130, br: 0.90 },
  { x: 370, y: 120, br: 0.90 }, { x: 380, y: 145, br: 0.90 },
  { x: 240, y: 45, br: 0.90 }, { x: 260, y: 55, br: 0.90 },
  { x: 100, y: 170, br: 0.90 }, { x: 120, y: 190, br: 0.90 }, { x: 90, y: 200, br: 0.90 }
]

// 道路网络（灰色背景线）
const roadNetwork = [
  { x1: 100, y1: 100, x2: 300, y2: 100 }, { x1: 150, y1: 50, x2: 250, y2: 250 },
  { x1: 100, y1: 200, x2: 400, y2: 150 }, { x1: 200, y1: 80, x2: 200, y2: 220 },
  { x1: 270, y1: 90, x2: 350, y2: 200 }, { x1: 120, y1: 160, x2: 280, y2: 160 },
  { x1: 170, y1: 120, x2: 370, y2: 120 }, { x1: 90, y1: 180, x2: 300, y2: 200 }
]

// 阻断道路（红色粗线）
const blockedRoads = [
  { x1: 155, y1: 95,  x2: 168, y2: 92,  op: 0.8 },
  { x1: 225, y1: 120, x2: 240, y2: 125, op: 0.8 },
  { x1: 265, y1: 130, x2: 280, y2: 128, op: 0.8 },
  { x1: 200, y1: 160, x2: 230, y2: 180, op: 0.8 },
  { x1: 340, y1: 200, x2: 345, y2: 225, op: 0.8 },
  { x1: 345, y1: 225, x2: 350, y2: 200, op: 0.6 },
  { x1: 345, y1: 225, x2: 330, y2: 230, op: 0.6 },
  { x1: 330, y1: 240, x2: 315, y2: 255, op: 0.8 },
  { x1: 270, y1: 135, x2: 265, y2: 142, op: 0.8 },
  { x1: 310, y1: 170, x2: 308, y2: 185, op: 0.8 }
]

// 烈度圈半径（6档震级）
const intensityRadii = [
  { vi: 15, v: 30, iv: 50 },
  { vi: 35, v: 70, iv: 110 },
  { vi: 50, v: 90, iv: 140 },
  { vi: 65, v: 115, iv: 170 },
  { vi: 80, v: 140, iv: 200 },
  { vi: 95, v: 165, iv: 230 }
]

// 关键路段表
const keyRoads = [
  { id: '#25821', len: '315m' },  { id: '#25675', len: '370m' },
  { id: '#33397', len: '315m' },  { id: '#37114', len: '2.4km' },
  { id: '#53086', len: '1.9km' }, { id: '#53087', len: '1.9km' },
  { id: '#53088', len: '810m' },  { id: '#53222', len: '1.6km' },
  { id: '#32683', len: '260m' },  { id: '#49223', len: '532m' }
]

// 地图工具
const mapTools = [
  { id: 'zoom-in', icon: ZoomIn, title: '放大' },
  { id: 'zoom-out', icon: ZoomOut, title: '缩小' },
  { id: 'home', icon: Home, title: '复位' },
  { id: 'identify', icon: MousePointerClick, title: '识别' },
  { id: 'measure', icon: Ruler, title: '测距' },
  { id: 'fullscreen', icon: Maximize, title: '全屏' }
]

// ==================== STATE ====================
const { magnitudes, currentMag, magIndex, setMagIndex } = useMagnitude()
const { data, loading, error } = useDashboardData()

const responseChartRef = ref(null)
let responseChart = null

const isPlaying = ref(false)
let playInterval = null

const isDragging = ref(false)
const scrubberTrackRef = ref(null)

const activeTool = ref('zoom-in')

const layers = ref([
  { id: 'intensity', name: '烈度场', active: true },
  { id: 'hospital', name: '医院可达性', active: true },
  { id: 'road', name: '关键路段', active: true }
])

// 映射到 MapContainer 的 layers 格式（02临界模式：区县/路网/阻断路网/医院/断裂带/烈度网格/震中）
const mapLayers = computed(() => ({
  districts: true,
  roads: true,
  blockedRoads: true,
  hospitals: isLayerActive('hospital'),
  rescue: false,
  shelters: false,
  hazards: false,
  fault: true,
  intensity: isLayerActive('intensity'),
  epicenter: true,
}))

const tooltipData = ref(null)
const tooltipStyle = ref({ left: 0, top: 0 })

// ==================== COMPUTED ====================
// 当前震级数据：优先从已加载 JSON 读取，回退到 allMagData
const currentData = computed(() => {
  const collapse = data.charts?.collapse
  const resilience = data.charts?.resilience
  if (collapse) {
    return {
      mag: currentMag.value,
      medical: collapse.medical_ratio,
      rescue: collapse.rescue_ratio,
      transport: collapse.transport_ratio,
      shelter: collapse.shelter_ratio > 1 ? 1.0 : collapse.shelter_ratio,
      resilience: resilience?.resilience_index ?? 0,
      medC: collapse.medical_collapse,
      resC: collapse.rescue_collapse,
      transC: collapse.transport_collapse,
      shelC: collapse.shelter_collapse,
      cityC: collapse.city_collapse,
    }
  }
  return allMagData.value[magIndex.value] || allMagData.value[1] || { mag: 5.5, medical: 0.268, rescue: 0.416, transport: 0.601, shelter: 1.0, resilience: 0.616, medC: true, resC: false, transC: false, shelC: false, cityC: true }
})

const currentRadii = computed(() => intensityRadii[magIndex.value])

// 区县数据：从 JSON 的 district_loss 构建
const districtData = computed(() => {
  const dl = data.charts?.district_loss
  if (!dl) return []
  const scale = EXPOSURE_SCALE.value || EXPOSURE_SCALE[magIndex.value]
  return dl.map(d => ({
    name: d.district,
    pop: d.population,
    exposed: Math.min(d.population, Math.round(d.exposed * scale)),
    affected: Math.round(d.exposed * scale * 0.05),
    loss: (d.loss * scale).toFixed(2),
    grids: 0,
    intensity: d.intensity
  }))
})

const totalExposed = computed(() => {
  if (data.kpi?.exposed_population != null) return data.kpi.exposed_population
  const total = districtData.value.reduce((sum, d) => sum + d.exposed, 0)
  return Math.min(total, 9885000)
})

const totalLoss = computed(() => {
  if (data.kpi?.economic_loss_yi != null) return data.kpi.economic_loss_yi
  return districtData.value.reduce((sum, d) => sum + parseFloat(d.loss), 0)
})

const totalAffected = computed(() => {
  if (data.kpi?.affected_population != null) return data.kpi.affected_population
  return districtData.value.reduce((sum, d) => sum + d.affected, 0)
})

// KPI Bar 8格
const kpiItems = computed(() => {
  const d = currentData.value
  return [
    { label: '当前震级', value: 'M' + d.mag.toFixed(1), color: 'accent' },
    { label: '医疗功能率', value: (d.medical * 100).toFixed(1) + '%', color: kpiColor(d.medical, d.medC) },
    { label: '救援功能率', value: (d.rescue * 100).toFixed(1) + '%', color: kpiColor(d.rescue, d.resC) },
    { label: '交通功能率', value: (d.transport * 100).toFixed(1) + '%', color: kpiColor(d.transport, d.transC) },
    { label: '避难功能率', value: (d.shelter * 100).toFixed(1) + '%', color: kpiColor(d.shelter, d.shelC) },
    { label: '暴露人口', value: (totalExposed.value / 10000).toFixed(0) + '万', color: 'accent' },
    { label: '经济损失', value: '¥' + totalLoss.value.toFixed(0) + '亿', color: 'accent' },
    { label: '韧性指数', value: d.resilience.toFixed(3), color: resilienceColor(d.resilience) }
  ]
})

// 4系统功能率条
const systemGauges = computed(() => {
  const d = currentData.value
  return [
    { name: '医疗', value: d.medical, collapsed: d.medC, color: sysColorVar(d.medical, d.medC) },
    { name: '救援', value: d.rescue, collapsed: d.resC, color: sysColorVar(d.rescue, d.resC) },
    { name: '交通', value: d.transport, collapsed: d.transC, color: sysColorVar(d.transport, d.transC) },
    { name: '避难', value: d.shelter, collapsed: d.shelC, color: sysColorVar(d.shelter, d.shelC) }
  ]
})

// 崩溃告警列表
const alerts = computed(() => {
  const d = currentData.value
  return [
    { name: '医疗', collapsed: d.medC },
    { name: '救援', collapsed: d.resC },
    { name: '交通', collapsed: d.transC },
    { name: '避难', collapsed: d.shelC },
    { name: '城市整体', collapsed: d.cityC }
  ]
})

// 状态横幅
const statusBanner = computed(() => {
  const d = currentData.value
  if (d.medC && !d.resC) {
    return { icon: Zap, color: 'var(--state-error)', bg: 'rgba(255, 68, 68,0.15)', border: 'rgba(255, 68, 68,0.3)', title: 'M' + d.mag.toFixed(1) + ' 医疗系统崩溃', desc: '功能率降至' + (d.medical * 100).toFixed(1) + '%，44%医院不可达' }
  } else if (d.resC && !d.shelC) {
    return { icon: AlertOctagon, color: 'var(--state-orange)', bg: 'rgba(255, 51, 102,0.15)', border: 'rgba(255, 51, 102,0.3)', title: 'M' + d.mag.toFixed(1) + ' 救援系统崩溃', desc: '医疗+救援双系统崩溃，级联传播中' }
  } else if (d.shelC) {
    return { icon: AlertTriangle, color: 'var(--state-error)', bg: 'rgba(255, 68, 68,0.15)', border: 'rgba(255, 68, 68,0.3)', title: 'M' + d.mag.toFixed(1) + ' 3系统级联崩溃', desc: '医疗/救援/避难崩溃，城市全面失能' }
  }
  return { icon: ShieldCheck, color: 'var(--state-success)', bg: 'rgba(0, 255, 148,0.15)', border: 'rgba(0, 255, 148,0.3)', title: 'M' + d.mag.toFixed(1) + ' 全系统正常', desc: '所有生命线系统功能率高于30%阈值' }
})

// 滑块stops
const scrubberStops = computed(() => {
  const src = allMagData.value.length > 0 ? allMagData.value : magnitudes.map(() => ({ cityC: false }))
  return src.map((d, i) => ({
    idx: i,
    left: (i * 20) + '%',
    collapsed: d.cityC,
    active: i === magIndex.value
  }))
})

// 区县损失排名
const districtRanking = computed(() => {
  if (districtData.value.length === 0) return []
  const sorted = [...districtData.value].sort((a, b) => parseFloat(b.loss) - parseFloat(a.loss))
  const maxLoss = parseFloat(sorted[0].loss)
  return sorted.filter(d => parseFloat(d.loss) > 0.01).map(d => {
    const loss = parseFloat(d.loss).toFixed(1)
    const pct = ((parseFloat(d.loss) / maxLoss) * 100).toFixed(0)
    const v = parseFloat(d.loss)
    const color = v > 50 ? 'var(--state-error)' : v > 20 ? 'var(--state-warning)' : 'var(--av-primary)'
    return { name: d.name, loss, pct, color }
  })
})

// 双档阈值对比表
const dualThresholdTable = computed(() => {
  if (!dualThreshold.value) return { rows: [], conservativeCritical: null, lenientCritical: null }
  const dt = dualThreshold.value
  const rows = dt.results.map(r => ({
    mag: r.magnitude,
    consCollapse: r.conservative.city_collapse,
    leniCollapse: r.lenient.city_collapse,
    consSystems: [
      { name: '医', collapsed: r.conservative.systems.medical },
      { name: '救', collapsed: r.conservative.systems.rescue },
      { name: '交', collapsed: r.conservative.systems.transport },
      { name: '避', collapsed: r.conservative.systems.shelter },
    ],
    leniSystems: [
      { name: '医', collapsed: r.lenient.systems.medical },
      { name: '救', collapsed: r.lenient.systems.rescue },
      { name: '交', collapsed: r.lenient.systems.transport },
      { name: '避', collapsed: r.lenient.systems.shelter },
    ],
  }))
  return {
    rows,
    conservativeCritical: dt.conservative_critical,
    lenientCritical: dt.lenient_critical,
    conclusion: dt.conclusion,
  }
})

// 韧性指数仪表
const resilienceInfo = computed(() => {
  const r = currentData.value.resilience
  const colorKey = resilienceColor(r)
  const label = r >= 0.65 ? '高韧性' : r >= 0.5 ? '中等韧性' : r >= 0.4 ? '较低韧性' : '低韧性'
  const colorVar = colorKey === 'green' ? 'var(--state-success)' : colorKey === 'yellow' ? 'var(--state-warning)' : colorKey === 'accent' ? 'var(--av-primary)' : 'var(--state-error)'
  const angle = (r - 0.5) * Math.PI
  const cx = 22, cy = 24, len = 12
  const needleX = cx + Math.sin(angle) * len
  const needleY = cy - Math.cos(angle) * len
  const startAngle = Math.PI
  const endAngle = startAngle + r * Math.PI
  const r2 = 18
  const x1 = cx + r2 * Math.cos(startAngle)
  const y1 = cy + r2 * Math.sin(startAngle)
  const xe = cx + r2 * Math.cos(endAngle)
  const ye = cy + r2 * Math.sin(endAngle)
  return {
    value: r.toFixed(3),
    label,
    colorVar,
    barWidth: (r * 100) + '%',
    needleX: needleX.toFixed(2),
    needleY: needleY.toFixed(2),
    arcPath: 'M' + x1.toFixed(2) + ',' + y1.toFixed(2) + ' A' + r2 + ',' + r2 + ' 0 0,1 ' + xe.toFixed(2) + ',' + ye.toFixed(2)
  }
})

// ==================== HELPER FUNCTIONS ====================
function kpiColor(value, collapsed) {
  if (collapsed) return 'red'
  if (value < 0.5) return 'orange'
  if (value < 0.8) return 'yellow'
  return 'green'
}

function resilienceColor(r) {
  if (r >= 0.65) return 'green'
  if (r >= 0.5) return 'yellow'
  if (r >= 0.4) return 'accent'
  return 'red'
}

function sysColorVar(value, collapsed) {
  if (collapsed) return 'var(--state-error)'
  if (value < 0.5) return 'var(--state-orange)'
  if (value < 0.8) return 'var(--state-warning)'
  return 'var(--state-success)'
}

function hospitalFill(baseReach) {
  const reach = baseReach * currentData.value.medical / 0.5423
  if (reach < 0.3) return '#FF4444'
  if (reach < 0.6) return '#FFB800'
  return '#00FF94'
}

function isHospitalUnreachable(baseReach) {
  const reach = baseReach * currentData.value.medical / 0.5423
  return reach < 0.3
}

function isLayerActive(id) {
  const layer = layers.value.find(l => l.id === id)
  return layer ? layer.active : false
}

function toggleLayer(layer) {
  layer.active = !layer.active
}

// ==================== CHART ====================
function getChartOption() {
  const idx = magIndex.value
  const magLabels = magnitudes.map(m => 'M' + m.toFixed(1))
  const chartData = allMagData.value.length > 0 ? allMagData.value : magnitudes.map(() => ({ medical: 0, rescue: 0, transport: 0, shelter: 0 }))
  return {
    grid: { left: 38, right: 18, top: 28, bottom: 25 },
    legend: {
      top: 0,
      textStyle: { color: '#5A6B82', fontSize: 9 },
      itemWidth: 10, itemHeight: 2,
      data: ['医疗', '救援', '交通', '避难']
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#0B1018',
      borderColor: '#1B2640',
      textStyle: { color: '#DCE6F0', fontSize: 10 },
      formatter: (params) => {
        let html = '<div style="color:#00D9FF;font-weight:600;margin-bottom:2px;">' + params[0].axisValue + '</div>'
        params.forEach(p => {
          html += '<div>' + p.marker + ' ' + p.seriesName + ': ' + p.value.toFixed(1) + '%</div>'
        })
        return html
      }
    },
    xAxis: {
      type: 'category',
      data: magLabels,
      axisLine: { lineStyle: { color: '#1E3A5F' } },
      axisLabel: { color: '#5A6B82', fontSize: 9 },
      axisTick: { show: false }
    },
    yAxis: {
      type: 'value',
      min: 0, max: 105,
      axisLine: { show: false },
      axisLabel: { color: '#5A6B82', fontSize: 9, formatter: '{value}%' },
      splitLine: { lineStyle: { color: '#1E3A5F' } }
    },
    series: [
      {
        name: '医疗', type: 'line', smooth: true,
        data: chartData.map(d => +((d.medical || 0) * 100).toFixed(1)),
        lineStyle: { color: '#FF4444', width: 2 },
        itemStyle: { color: '#FF4444' },
        symbol: 'circle',
        symbolSize: (val, params) => params.dataIndex === idx ? 8 : 5
      },
      {
        name: '救援', type: 'line', smooth: true,
        data: chartData.map(d => +((d.rescue || 0) * 100).toFixed(1)),
        lineStyle: { color: '#FF3366', width: 2 },
        itemStyle: { color: '#FF3366' },
        symbol: 'circle',
        symbolSize: (val, params) => params.dataIndex === idx ? 8 : 5
      },
      {
        name: '交通', type: 'line', smooth: true,
        data: chartData.map(d => +((d.transport || 0) * 100).toFixed(1)),
        lineStyle: { color: '#FFB800', width: 2 },
        itemStyle: { color: '#FFB800' },
        symbol: 'circle',
        symbolSize: (val, params) => params.dataIndex === idx ? 8 : 5
      },
      {
        name: '避难', type: 'line', smooth: true,
        data: chartData.map(d => {
          const v = d.shelter || 0
          return +(Math.min(v, 1.0) * 100).toFixed(1)
        }),
        lineStyle: { color: '#00FF94', width: 2 },
        itemStyle: { color: '#00FF94' },
        symbol: 'circle',
        symbolSize: (val, params) => params.dataIndex === idx ? 8 : 5,
        markLine: {
          silent: true,
          symbol: ['none', 'none'],
          data: [
            {
              yAxis: 30,
              lineStyle: { color: '#FF4444', type: 'dashed', width: 1, opacity: 0.5 },
              label: { show: true, formatter: '30%阈值', color: '#FF4444', fontSize: 8, position: 'end' }
            },
            {
              xAxis: idx,
              lineStyle: { color: '#00D9FF', type: 'dashed', width: 1, opacity: 0.4 }
            }
          ]
        }
      }
    ]
  }
}

function initChart() {
  if (!responseChartRef.value) return
  if (responseChart) return  // 防止重复初始化
  const w = responseChartRef.value.clientWidth
  const h = responseChartRef.value.clientHeight
  responseChart = echarts.init(responseChartRef.value, null, { width: w || 300, height: h || 150 })
  responseChart.setOption(getChartOption())
  requestAnimationFrame(() => responseChart && responseChart.resize())
}

function updateChart() {
  if (!responseChart) return
  responseChart.setOption(getChartOption(), { notMerge: true })
}

function handleResize() {
  if (responseChart) responseChart.resize()
}

// ==================== SCRUBBER INTERACTION ====================
function onScrubberMouseDown(e) {
  isDragging.value = true
  updateScrubberFromX(e.clientX)
}

function onScrubberMouseMove(e) {
  if (isDragging.value) updateScrubberFromX(e.clientX)
}

function onScrubberMouseUp() {
  isDragging.value = false
}

function updateScrubberFromX(clientX) {
  if (!scrubberTrackRef.value) return
  const rect = scrubberTrackRef.value.getBoundingClientRect()
  const pct = (clientX - rect.left) / rect.width
  const idx = Math.max(0, Math.min(5, Math.round(pct * 5)))
  setMagIndex(idx)
}

function onStopClick(idx) {
  setMagIndex(idx)
}

// ==================== PLAY / PAUSE / RESET ====================
function togglePlay() {
  if (isPlaying.value) {
    pausePlay()
  } else {
    startPlay()
  }
}

function startPlay() {
  isPlaying.value = true
  playInterval = setInterval(() => {
    const next = (magIndex.value + 1) % 6
    setMagIndex(next)
  }, 1500)
}

function pausePlay() {
  isPlaying.value = false
  if (playInterval) {
    clearInterval(playInterval)
    playInterval = null
  }
}

function resetPlay() {
  pausePlay()
  setMagIndex(0)
}

// ==================== DISTRICT TOOLTIP ====================
function showTooltip(district, event) {
  const dist = districtData.value.find(d => d.name === district.name)
  if (!dist) return
  tooltipData.value = {
    name: district.name,
    intensity: district.il,
    intensityLevel: dist.intensity >= 6 ? 'VI' : dist.intensity >= 5 ? 'V' : 'IV',
    pop: (dist.pop / 10000).toFixed(1) + '万',
    exposed: (dist.exposed / 10000).toFixed(1) + '万',
    loss: '¥' + parseFloat(dist.loss).toFixed(1) + '亿',
    avgIntensity: dist.intensity,
    grids: dist.grids
  }
  moveTooltip(event)
}

function moveTooltip(event) {
  const container = event.currentTarget.closest('.map-container')
  if (!container) return
  const rect = container.getBoundingClientRect()
  tooltipStyle.value = {
    left: event.clientX - rect.left + 15,
    top: event.clientY - rect.top + 15
  }
}

function hideTooltip() {
  tooltipData.value = null
}

// ==================== WATCHER ====================
watch(magIndex, () => {
  updateChart()
})

// allMagData 加载完成后刷新图表
watch(allMagData, () => {
  updateChart()
})

// 当数据加载完成、内容渲染后初始化图表（处理 v-if/v-else 时序问题）
watch(() => !loading.value && !!data.kpi, (visible) => {
  if (visible) {
    nextTick(() => initChart())
  }
})

// ==================== LIFECYCLE ====================
onMounted(async () => {
  await loadAllMagData()
  loadDualThreshold()
  nextTick(() => {
    initChart()
  })
  document.addEventListener('mousemove', onScrubberMouseMove)
  document.addEventListener('mouseup', onScrubberMouseUp)
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  document.removeEventListener('mousemove', onScrubberMouseMove)
  document.removeEventListener('mouseup', onScrubberMouseUp)
  window.removeEventListener('resize', handleResize)
  if (responseChart) responseChart.dispose()
  if (playInterval) clearInterval(playInterval)
})
</script>

<template>
  <div class="mode-root">
  <div v-if="loading && !data.kpi" class="loading-overlay">
    <Loader2 :size="24" class="spin" />
    <span style="margin-left:8px;font-size:12px;color:var(--av-muted-foreground);">加载临界数据...</span>
  </div>
  <div v-else>
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
        <!-- 实时推演探针 -->
        <RealtimeProbe />

        <!-- Status Banner -->
        <div class="status-banner" :style="{ borderColor: statusBanner.border }">
          <div class="status-banner-icon" :style="{ background: statusBanner.bg }">
            <component :is="statusBanner.icon" class="w-4 h-4" :style="{ color: statusBanner.color }" />
          </div>
          <div class="status-banner-text">
            <div class="status-banner-title">{{ statusBanner.title }}</div>
            <div class="status-banner-desc">{{ statusBanner.desc }}</div>
          </div>
        </div>

        <!-- Scrubber -->
        <div class="scrubber-box">
          <div class="scrubber-display">
            <div class="scrubber-value">{{ currentMag.toFixed(1) }}</div>
            <div class="scrubber-label">MAGNITUDE · 里氏震级</div>
          </div>
          <div
            class="scrubber-track"
            ref="scrubberTrackRef"
            @mousedown="onScrubberMouseDown"
          >
            <div class="scrubber-line"></div>
            <div class="scrubber-fill" :style="{ width: (magIndex * 20) + '%' }"></div>
            <div
              v-for="stop in scrubberStops"
              :key="stop.idx"
              class="scrubber-stop"
              :class="{ collapsed: stop.collapsed, active: stop.active }"
              :style="{ left: stop.left }"
              @click.stop="onStopClick(stop.idx)"
            ></div>
          </div>
          <div class="scrubber-labels">
            <span v-for="m in magnitudes" :key="m">{{ m.toFixed(1) }}</span>
          </div>
          <div class="scrubber-controls">
            <div class="scr-btn" :class="{ active: isPlaying }" @click="togglePlay">
              <component :is="isPlaying ? Pause : Play" class="w-3 h-3" />
              {{ isPlaying ? '暂停' : '播放' }}
            </div>
            <div class="scr-btn" @click="resetPlay">
              <RotateCcw class="w-3 h-3" />
              重置
            </div>
          </div>
        </div>

        <!-- System Gauges -->
        <div class="section-label">4系统功能率</div>
        <div v-for="g in systemGauges" :key="g.name" class="sys-row">
          <span class="sys-name" :style="{ color: g.color }">{{ g.name }}</span>
          <div class="sys-bar-wrap">
            <div class="sys-bar-fill" :style="{ width: (g.value * 100).toFixed(1) + '%', background: g.color }"></div>
            <div class="sys-threshold" style="left:30%;"></div>
          </div>
          <span class="sys-val" :style="{ color: g.color }">{{ (g.value * 100).toFixed(1) }}%</span>
        </div>

        <!-- Collapse Alerts -->
        <div class="section-label">崩溃告警</div>
        <div>
          <div
            v-for="a in alerts"
            :key="a.name"
            class="alert-item"
            :class="a.collapsed ? 'red' : 'green'"
          >
            <span
              class="alert-dot"
              :style="{ background: a.collapsed ? 'var(--state-error)' : 'var(--state-success)' }"
            ></span>
            {{ a.name }}{{ a.name === '城市整体' ? '' : '系统' }}{{ a.collapsed ? '已崩溃' : '正常' }}
          </div>
        </div>

        <!-- Layers -->
        <div class="section-label">图层</div>
        <div class="flex flex-col gap-1">
          <div
            v-for="layer in layers"
            :key="layer.id"
            class="flex items-center gap-2 text-xs cursor-pointer"
            style="padding:2px 4px;"
            :style="{ color: layer.active ? 'var(--av-foreground)' : 'var(--av-muted-foreground)' }"
            @click="toggleLayer(layer)"
          >
            <component
              :is="layer.active ? CheckSquare : Square"
              class="w-3.5 h-3.5"
              :style="{ color: layer.active ? 'var(--av-primary)' : '' }"
            />
            <span>{{ layer.name }}</span>
          </div>
        </div>
      </div>

      <!-- === Center: Map + Bottom Panels === -->
      <div class="col-center">
        <div class="map-container">
          <!-- Leaflet Map -->
          <MapContainer
            :magnitude="currentMag"
            :layers="mapLayers"
            class="map-leaflet"
          />

          <!-- Map Toolbar -->
          <div class="map-toolbar">
            <div class="map-info">拖动震级滑块查看烈度场变化 · 悬停区县查看详情</div>
          </div>

          <!-- Legend -->
          <div class="map-legend">
            <div><span style="color:#FF4444;">●</span>医院不可达 <span style="color:#FFB800;">●</span>部分可达 <span style="color:#00FF94;">●</span>可达</div>
            <div><span style="color:#FF4444;">━</span>关键路段(阻断) <span style="color:#5A6B82;">─</span>断裂带</div>
            <div><span style="color:#FF4444;">◎</span>VI度 <span style="color:#FFB800;">◎</span>V度 <span style="color:#00FF94;">◎</span>IV度</div>
          </div>

          <!-- District Tooltip -->
          <div
            v-if="tooltipData"
            class="district-tooltip"
            :style="{ display: 'block', left: tooltipStyle.left + 'px', top: tooltipStyle.top + 'px' }"
          >
            <div style="color:var(--av-primary);font-weight:600;margin-bottom:4px;">{{ tooltipData.name }} · 烈度{{ tooltipData.intensityLevel }}</div>
            <div style="border-top:1px solid var(--av-border);margin-bottom:4px;"></div>
            <div style="display:flex;justify-content:space-between;color:var(--av-muted-foreground);"><span>总人口</span><span style="color:var(--av-foreground);font-family:var(--av-font-mono);">{{ tooltipData.pop }}</span></div>
            <div style="display:flex;justify-content:space-between;color:var(--av-muted-foreground);"><span>暴露人口</span><span style="color:var(--state-error);font-family:var(--av-font-mono);">{{ tooltipData.exposed }}</span></div>
            <div style="display:flex;justify-content:space-between;color:var(--av-muted-foreground);"><span>经济损失</span><span style="color:var(--state-error);font-family:var(--av-font-mono);">{{ tooltipData.loss }}</span></div>
            <div style="display:flex;justify-content:space-between;color:var(--av-muted-foreground);"><span>平均烈度</span><span style="color:var(--av-foreground);font-family:var(--av-font-mono);">{{ tooltipData.avgIntensity }}</span></div>
            <div style="display:flex;justify-content:space-between;color:var(--av-muted-foreground);"><span>网格数</span><span style="color:var(--av-foreground);font-family:var(--av-font-mono);">{{ tooltipData.grids }}</span></div>
          </div>
        </div>

        <!-- Bottom Panels -->
        <div class="bottom-panels">
          <!-- Response Curves Chart -->
          <div class="chart-panel">
            <div class="chart-panel-title">
              <span>4系统功能率响应曲线 · 6震级</span>
              <span style="color:var(--state-error);font-size:10px;">━ 30% 崩溃阈值</span>
            </div>
            <div class="chart-body">
              <div ref="responseChartRef" style="width:100%;height:100%;"></div>
            </div>
          </div>

          <!-- Collapse Threshold Table -->
          <div class="chart-panel">
            <div class="chart-panel-title">
              <span>崩溃阈值表 · 6震级</span>
              <span style="color:var(--state-error);font-size:10px;">红色=崩溃</span>
            </div>
            <div class="chart-body" style="overflow-y:auto;">
              <table class="mini-table">
                <tbody>
                <tr>
                  <th>震级</th>
                  <th>医疗</th>
                  <th>救援</th>
                  <th>交通</th>
                  <th>避难</th>
                  <th>城市</th>
                </tr>
                <tr
                  v-for="(d, i) in allMagData"
                  :key="i"
                  :class="{ highlight: i === magIndex }"
                >
                  <td>M{{ d.mag.toFixed(1) }}</td>
                  <td :style="{ color: d.medC ? 'var(--state-error)' : 'var(--state-success)' }">{{ d.medC ? '崩' : '正常' }}</td>
                  <td :style="{ color: d.resC ? 'var(--state-error)' : 'var(--state-success)' }">{{ d.resC ? '崩' : '正常' }}</td>
                  <td :style="{ color: d.transC ? 'var(--state-error)' : 'var(--state-success)' }">{{ d.transC ? '崩' : '正常' }}</td>
                  <td :style="{ color: d.shelC ? 'var(--state-error)' : 'var(--state-success)' }">{{ d.shelC ? '崩' : '正常' }}</td>
                  <td :style="{ color: d.cityC ? 'var(--state-error)' : 'var(--state-success)' }">{{ d.cityC ? '崩' : '正常' }}</td>
                </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>

      <!-- === Right Panel === -->
      <div class="col-panel">
        <!-- District Loss Ranking -->
        <div class="panel-item red">
          <div class="panel-label">9区县损失排名 · M{{ currentMag.toFixed(1) }}</div>
          <template v-for="d in districtRanking" :key="d.name">
            <div class="data-row">
              <span class="data-row-key">{{ d.name }}</span>
              <span class="data-row-val" :style="{ color: d.color }">¥{{ d.loss }}M</span>
            </div>
            <div class="bar-mini">
              <div class="bar-mini-fill" :style="{ width: d.pct + '%', background: d.color }"></div>
            </div>
          </template>
        </div>

        <!-- Summary -->
        <div class="panel-item accent">
          <div class="panel-label">震级汇总</div>
          <div class="data-row"><span class="data-row-key">暴露人口</span><span class="data-row-val" style="color:var(--av-primary);">{{ (totalExposed / 10000).toFixed(1) }}万</span></div>
          <div class="data-row"><span class="data-row-key">受灾人口</span><span class="data-row-val">{{ (totalAffected / 10000).toFixed(1) }}万</span></div>
          <div class="data-row"><span class="data-row-key">经济损失</span><span class="data-row-val" style="color:var(--state-error);">¥{{ totalLoss.toFixed(0) }}亿</span></div>
          <div class="data-row"><span class="data-row-key">平均损失率</span><span class="data-row-val" style="color:var(--state-warning);">{{ ((totalLoss / 11000) * 100).toFixed(1) }}%</span></div>
          <div class="data-row">
            <span class="data-row-key">城市状态</span>
            <span class="tag" :class="currentData.cityC ? 'tag-red' : 'tag-green'">{{ currentData.cityC ? '已崩溃' : '正常' }}</span>
          </div>
        </div>

        <!-- Resilience -->
        <div class="panel-item">
          <div class="panel-label">韧性指数</div>
          <div class="flex items-center gap-2">
            <svg width="44" height="28" viewBox="0 0 44 28">
              <path d="M4,24 A18,18 0 0,1 40,24" fill="none" stroke="#1E3A5F" stroke-width="2.5" />
              <path :d="resilienceInfo.arcPath" fill="none" :stroke="resilienceInfo.colorVar" stroke-width="2.5" stroke-linecap="round" />
              <line :x1="22" y1="24" :x2="resilienceInfo.needleX" :y2="resilienceInfo.needleY" :stroke="resilienceInfo.colorVar" stroke-width="1.5" stroke-linecap="round" />
              <circle cx="22" cy="24" r="2" :fill="resilienceInfo.colorVar" />
            </svg>
            <div>
              <div style="font-size:18px;font-weight:700;font-family:var(--av-font-mono);" :style="{ color: resilienceInfo.colorVar }">{{ resilienceInfo.value }}</div>
              <div style="font-size:9px;color:var(--av-muted-foreground);">{{ resilienceInfo.label }}</div>
            </div>
          </div>
          <div class="bar-mini" style="margin-top:4px;">
            <div class="bar-mini-fill" :style="{ width: resilienceInfo.barWidth, background: resilienceInfo.colorVar }"></div>
          </div>
          <div style="display:flex;justify-content:space-between;font-size:8px;color:var(--av-muted-foreground);margin-top:2px;">
            <span>0.0 低</span><span>0.4</span><span>0.6</span><span>1.0 高</span>
          </div>
        </div>

        <!-- Dual Threshold Comparison -->
        <div class="panel-item" v-if="dualThresholdTable.rows.length">
          <div class="panel-label">双档阈值敏感性</div>
          <div style="display:flex;gap:6px;margin-bottom:6px;">
            <div style="flex:1;padding:4px 6px;border:1px solid var(--av-border);border-radius:4px;background:rgba(255,68,68,0.06);">
              <div style="font-size:8px;color:var(--av-muted-foreground);">保守阈值</div>
              <div style="font-size:14px;font-weight:700;color:var(--state-error);font-family:var(--av-font-mono);">M{{ dualThresholdTable.conservativeCritical?.toFixed(1) }}</div>
              <div style="font-size:7px;color:var(--av-muted-foreground);">医&lt;.30 救&lt;.40</div>
            </div>
            <div style="flex:1;padding:4px 6px;border:1px solid var(--av-border);border-radius:4px;background:rgba(255,184,0,0.06);">
              <div style="font-size:8px;color:var(--av-muted-foreground);">宽松阈值</div>
              <div style="font-size:14px;font-weight:700;color:var(--state-warning);font-family:var(--av-font-mono);">M{{ dualThresholdTable.lenientCritical?.toFixed(1) }}</div>
              <div style="font-size:7px;color:var(--av-muted-foreground);">医&lt;.50 救&lt;.50</div>
            </div>
          </div>
          <table class="mini-table dual-thresh-table">
            <tbody>
              <tr>
                <th>M</th>
                <th colspan="2">保守</th>
                <th colspan="2">宽松</th>
              </tr>
              <tr v-for="row in dualThresholdTable.rows" :key="row.mag">
                <td>{{ row.mag.toFixed(1) }}</td>
                <td :class="row.consCollapse ? 'cell-red' : 'cell-green'">{{ row.consCollapse ? '崩' : '正' }}</td>
                <td style="font-size:7px;">
                  <span v-for="(s, i) in row.consSystems" :key="i" :style="{ color: s.collapsed ? 'var(--state-error)' : 'var(--av-muted-foreground)' }">{{ s.name }}</span>
                </td>
                <td :class="row.leniCollapse ? 'cell-red' : 'cell-green'">{{ row.leniCollapse ? '崩' : '正' }}</td>
                <td style="font-size:7px;">
                  <span v-for="(s, i) in row.leniSystems" :key="i" :style="{ color: s.collapsed ? 'var(--state-error)' : 'var(--av-muted-foreground)' }">{{ s.name }}</span>
                </td>
              </tr>
            </tbody>
          </table>
          <div style="font-size:8px;color:var(--av-muted-foreground);margin-top:4px;line-height:1.4;">
            独立评估临界 M6.5 → 级联后两档均提前，证明结论不依赖阈值设定
          </div>
        </div>
      </div>

    </div>
  </div>
  </div>
</template>

<style scoped>
.loading-overlay {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
  min-height: 200px;
}
.spin {
  animation: th-spin 1s linear infinite;
}
@keyframes th-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
.dual-thresh-table td.cell-red {
  color: var(--state-error);
  font-weight: 700;
  font-size: 10px;
}
.dual-thresh-table td.cell-green {
  color: var(--state-success);
  font-size: 10px;
}
.dual-thresh-table th {
  font-size: 8px;
  color: var(--av-muted-foreground);
  font-weight: 400;
  padding: 2px 3px;
}
.dual-thresh-table td {
  text-align: center;
  padding: 2px 3px;
}
</style>
