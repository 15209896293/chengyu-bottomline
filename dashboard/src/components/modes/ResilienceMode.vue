<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import echarts from '../../engine/echartsSetup.js'
import {
  ShieldCheck, Shield, ShieldOff,
  CheckSquare, Square,
  ZoomIn, ZoomOut, Home, MousePointerClick, Ruler, Maximize,
  Loader2,
  SlidersHorizontal, TrendingUp
} from 'lucide-vue-next'
import { useDashboardData } from '../../composables/useDashboardData.js'
import { useMagnitude } from '../../composables/useMagnitude.js'
import MapContainer from '../map/MapContainer.vue'

// ==================== 决策舱：预算 → 底线推移 ====================
const decision = ref(null)
const budgetSlider = ref(2.0) // 默认 2 亿（首个能推高底线的预算）

async function loadDecision() {
  try {
    const r = await fetch(import.meta.env.BASE_URL + 'data/decision_support.json')
    if (r.ok) decision.value = await r.json()
  } catch (e) { console.error('加载决策数据失败:', e) }
}

const currentDecision = computed(() => {
  const d = decision.value
  if (!d?.budget_curve?.length) return null
  // 找预算档位（最近 ≤ 滑块的档）
  const target = budgetSlider.value
  const pts = d.budget_curve
  let best = pts[0]
  for (const p of pts) {
    if (p.budget <= target + 1e-9) best = p
    else break
  }
  // 下一档（看再加钱能否推高）
  const next = pts.find(p => p.budget > best.budget + 1e-9 && p.bottom_line_mag > best.bottom_line_mag)
  return { current: best, next, baseline: d.baseline?.bottom_line_mag ?? 6.0 }
})

// ---- 底线推移曲线图 ----
const decisionChartRef = ref(null)
let decisionChart = null

function renderDecisionChart() {
  if (!decisionChartRef.value || !decision.value?.budget_curve) return
  decisionChart = decisionChart || echarts.init(decisionChartRef.value)
  const curve = decision.value.budget_curve
  const baseline = decision.value.baseline?.bottom_line_mag ?? 6.0
  const cur = currentDecision.value?.current
  decisionChart.setOption({
    backgroundColor: 'transparent',
    grid: { left: 38, right: 14, top: 26, bottom: 22 },
    tooltip: { trigger: 'axis', backgroundColor: '#0B1018', borderColor: '#1B2640', textStyle: { color: '#DCE6F0', fontSize: 11 }, formatter: p => {
      const d = curve[p[0].dataIndex]
      return `预算 ${d.budget} 亿<br/>底线 M${d.bottom_line_mag.toFixed(1)}（+${d.shift.toFixed(1)}）<br/>加固 ${d.roads} 路段 · 医疗 +${(d.gain_medical * 100).toFixed(1)}%`
    } },
    title: { text: '预算 → 城市崩溃底线（级联口径）', left: 8, top: 2, textStyle: { color: '#5A6B82', fontSize: 11, fontWeight: 600 } },
    xAxis: { type: 'category', data: curve.map(c => c.budget), name: '预算(亿)', nameTextStyle: { color: '#5A6B82', fontSize: 9 }, axisLabel: { color: '#5A6B82', fontSize: 9, interval: 3 }, axisLine: { lineStyle: { color: '#1B2640' } } },
    yAxis: { type: 'value', min: 5.5, max: 7.5, name: '底线震级', nameTextStyle: { color: '#5A6B82', fontSize: 9 }, axisLabel: { color: '#5A6B82', fontSize: 9, formatter: 'M{v}' }, splitLine: { lineStyle: { color: 'rgba(42,37,32,0.5)' } } },
    series: [{
      type: 'line', data: curve.map(c => c.bottom_line_mag), smooth: true, symbolSize: 5,
      lineStyle: { color: '#00D9FF', width: 2.5 }, itemStyle: { color: '#00D9FF' },
      markLine: {
        silent: true, symbol: 'none', label: { color: '#FF4444', fontSize: 9, formatter: '基线 M' + baseline.toFixed(1), position: 'insideEndTop' },
        lineStyle: { color: '#FF4444', type: 'dashed' }, data: [{ yAxis: baseline }],
      },
      markPoint: cur ? { symbol: 'pin', symbolSize: 34, label: { color: '#060912', fontSize: 9, fontWeight: 700, formatter: 'M' + cur.bottom_line_mag.toFixed(1) }, itemStyle: { color: '#00D9FF' }, data: [{ coord: [curve.findIndex(c => c.budget === cur.budget), cur.bottom_line_mag] }] } : undefined,
    }],
  }, true)
}

watch(budgetSlider, () => nextTick(renderDecisionChart))
watch(decision, () => nextTick(renderDecisionChart))

// ==================== DATA SOURCE ====================
const { data, loading, error } = useDashboardData()
const { currentMag } = useMagnitude()

// ==================== STRATEGY METADATA (visual only) ====================
const STRATEGY_META = {
  baseline: { name: 'Baseline', nameCn: '基线', color: 'muted', colorVar: 'var(--av-muted-foreground)', icon: ShieldOff, investment: 0 },
  A: { name: '策略A', nameCn: '加固路段', color: 'yellow', colorVar: 'var(--state-warning)', icon: Shield, investment: 2.3 },
  B: { name: '策略B', nameCn: '增设医疗', color: 'orange', colorVar: 'var(--state-orange)', icon: Shield, investment: 0.8 },
  C: { name: '策略C', nameCn: 'A+B组合', color: 'green', colorVar: 'var(--state-success)', icon: ShieldCheck, investment: 3.1 },
}

// 从 JSON 构建策略数据
const STRATEGIES = computed(() => {
  const arr = data.prevention?.strategies
  if (!arr) return {}
  const result = {}
  for (const s of arr) {
    const meta = STRATEGY_META[s.strategy] || STRATEGY_META.baseline
    const shift = parseFloat(s.threshold_shift) || 0
    const investmentItems = []
    if (s.key_roads_repaired > 0) investmentItems.push({ label: '路段加固', amount: 2.3, color: 'var(--state-warning)' })
    if (s.temp_medical_points_added > 0) investmentItems.push({ label: '医疗增设', amount: 0.8, color: 'var(--state-orange)' })

    result[s.strategy] = {
      key: s.strategy,
      name: meta.name, nameCn: meta.nameCn,
      desc: s.description, fullDesc: s.description,
      color: meta.color, colorVar: meta.colorVar, icon: meta.icon,
      investment: meta.investment, investmentItems,
      medical: s.medical_ratio_before, rescue: s.rescue_ratio_before,
      medicalAfter: s.medical_ratio_after, rescueAfter: s.rescue_ratio_after,
      cityCollapseAfter: s.city_collapse_after,
      thresholdShift: shift,
      roi: shift > 0 ? Math.round((shift * 10 / Math.max(meta.investment, 0.1)) * 10) / 10 : 0,
      score: s.city_collapse_after ? 0.62 : (shift > 0 ? (s.strategy === 'C' ? 0.82 : 0.78) : 0.63),
      paybackPeriod: shift > 0 ? (s.strategy === 'C' ? 0.4 : 0.3) : null,
      recommended: s.strategy === 'C'
    }
  }
  return result
})

const STRATEGY_LIST = ['baseline', 'A', 'B', 'C']

const DISTRICT_IMPROVEMENT = {
  baseline: { '长丰县': 0, '肥东县': 0, '巢湖市': 0, '庐江县': 0, '肥西县': 0, '蜀山区': 0, '庐阳区': 0, '瑶海区': 0, '包河区': 0 },
  A: { '长丰县': 0.1, '肥东县': 0.2, '巢湖市': 0, '庐江县': 0, '肥西县': 0.1, '蜀山区': 0.3, '庐阳区': 0.6, '瑶海区': 0.65, '包河区': 0.25 },
  B: { '长丰县': 0, '肥东县': 0.05, '巢湖市': 0, '庐江县': 0, '肥西县': 0, '蜀山区': 0.1, '庐阳区': 0.2, '瑶海区': 0.15, '包河区': 0.05 },
  C: { '长丰县': 0.1, '肥东县': 0.25, '巢湖市': 0, '庐江县': 0, '肥西县': 0.1, '蜀山区': 0.35, '庐阳区': 0.7, '瑶海区': 0.75, '包河区': 0.3 }
}

const DISTRICT_ORIGINAL = {
  '长丰县': { fill: 'rgba(0, 255, 148,0.04)', stroke: '#1E3A5F', sw: 0.5 },
  '肥东县': { fill: 'rgba(255, 184, 0,0.04)', stroke: '#1E3A5F', sw: 0.5 },
  '巢湖市': { fill: 'rgba(0, 255, 148,0.02)', stroke: '#1E3A5F', sw: 0.5 },
  '庐江县': { fill: 'rgba(0, 255, 148,0.01)', stroke: '#1E3A5F', sw: 0.5 },
  '肥西县': { fill: 'rgba(0, 255, 148,0.03)', stroke: '#1E3A5F', sw: 0.5 },
  '蜀山区': { fill: 'rgba(255, 184, 0,0.06)', stroke: '#1E3A5F', sw: 0.5 },
  '庐阳区': { fill: 'rgba(255, 68, 68,0.08)', stroke: '#FF4444', sw: 0.6 },
  '瑶海区': { fill: 'rgba(255, 68, 68,0.1)', stroke: '#FF4444', sw: 0.6 },
  '包河区': { fill: 'rgba(255, 184, 0,0.06)', stroke: '#1E3A5F', sw: 0.5 }
}

const DISTRICTS = [
  { name: '长丰县', d: 'M150,20 Q220,15 290,25 Q310,50 295,75 Q230,80 170,70 Q140,50 150,20Z', tx: 220, ty: 48, highlight: false },
  { name: '肥东县', d: 'M295,75 Q360,70 410,90 Q420,130 400,170 Q350,175 300,160 Q285,120 295,75Z', tx: 350, ty: 120, highlight: false },
  { name: '巢湖市', d: 'M380,180 Q440,175 465,210 Q470,250 440,265 Q390,260 370,230 Q365,200 380,180Z', tx: 415, ty: 225, highlight: false },
  { name: '庐江县', d: 'M230,230 Q290,225 340,245 Q345,270 310,275 Q250,272 215,260 Q210,240 230,230Z', tx: 275, ty: 258, highlight: false },
  { name: '肥西县', d: 'M80,150 Q140,145 175,165 Q180,210 150,240 Q100,245 65,220 Q55,180 80,150Z', tx: 115, ty: 200, highlight: false },
  { name: '蜀山区', d: 'M110,80 Q160,75 175,100 Q180,130 160,150 Q120,155 95,135 Q85,105 110,80Z', tx: 132, ty: 115, highlight: false },
  { name: '庐阳区', d: 'M170,70 Q220,65 240,85 Q245,110 225,130 Q190,135 170,115 Q160,90 170,70Z', tx: 200, ty: 100, highlight: true },
  { name: '瑶海区', d: 'M240,85 Q285,80 300,100 Q305,125 285,145 Q250,150 235,125 Q230,100 240,85Z', tx: 265, ty: 112, highlight: true },
  { name: '包河区', d: 'M175,130 Q230,125 260,145 Q270,175 245,195 Q200,200 170,180 Q155,155 175,130Z', tx: 210, ty: 162, highlight: false }
]

const HOSPITALS = [
  { x: 190, y: 90, r: 0.4 }, { x: 198, y: 95, r: 0.4 }, { x: 195, y: 105, r: 0.4 },
  { x: 205, y: 92, r: 0.35 }, { x: 210, y: 100, r: 0.3 }, { x: 215, y: 108, r: 0.3 },
  { x: 200, y: 115, r: 0.4 }, { x: 220, y: 105, r: 0.35 }, { x: 225, y: 115, r: 0.3 },
  { x: 185, y: 105, r: 0.4 }, { x: 190, y: 118, r: 0.4 }, { x: 215, y: 120, r: 0.35 },
  { x: 250, y: 100, r: 0.35 }, { x: 260, y: 108, r: 0.3 }, { x: 268, y: 115, r: 0.3 },
  { x: 255, y: 120, r: 0.35 }, { x: 270, y: 125, r: 0.3 }, { x: 245, y: 115, r: 0.35 },
  { x: 275, y: 105, r: 0.3 }, { x: 282, y: 115, r: 0.3 },
  { x: 120, y: 100, r: 0.6 }, { x: 130, y: 105, r: 0.6 }, { x: 125, y: 115, r: 0.6 },
  { x: 115, y: 120, r: 0.65 }, { x: 140, y: 110, r: 0.6 }, { x: 135, y: 125, r: 0.6 },
  { x: 195, y: 150, r: 0.6 }, { x: 210, y: 155, r: 0.55 }, { x: 220, y: 165, r: 0.55 },
  { x: 200, y: 170, r: 0.6 }, { x: 230, y: 175, r: 0.55 },
  { x: 320, y: 100, r: 0.9 }, { x: 350, y: 110, r: 0.9 }, { x: 340, y: 130, r: 0.9 },
  { x: 370, y: 120, r: 0.9 }, { x: 380, y: 145, r: 0.9 },
  { x: 240, y: 45, r: 0.9 }, { x: 260, y: 55, r: 0.9 },
  { x: 100, y: 170, r: 0.9 }, { x: 120, y: 190, r: 0.9 }, { x: 90, y: 200, r: 0.9 }
]

const ROADS = [
  { x1: 155, y1: 95, x2: 168, y2: 92 },
  { x1: 225, y1: 120, x2: 240, y2: 125 },
  { x1: 265, y1: 130, x2: 280, y2: 128 },
  { x1: 200, y1: 160, x2: 230, y2: 180 },
  { x1: 340, y1: 200, x2: 345, y2: 225 },
  { x1: 345, y1: 225, x2: 350, y2: 200 },
  { x1: 345, y1: 225, x2: 330, y2: 230 },
  { x1: 330, y1: 240, x2: 315, y2: 255 },
  { x1: 270, y1: 135, x2: 265, y2: 142 },
  { x1: 310, y1: 170, x2: 308, y2: 185 }
]

const NEW_MEDICAL_POINTS = [
  { x: 195, y: 95 },
  { x: 258, y: 118 },
  { x: 228, y: 135 }
]

// 从 magnitude_curve 动态计算各策略韧性趋势偏移量
const RESILIENCE_TRENDS = computed(() => {
  const mc = data.charts?.magnitude_curve
  if (!mc || mc.length < 2) return { baseline: [], A: [], B: [], C: [] }
  const baseline = mc.map(d => d.resilience)
  // 从 magnitude_curve 推导每步长（0.5M）的平均韧性下降量，作为偏移基准
  const magStep = mc[1].magnitude - mc[0].magnitude || 0.5
  const avgDrop = (baseline[0] - baseline[baseline.length - 1]) / (baseline.length - 1)
  // 从 prevention.strategies 读取各策略 threshold_shift
  const strategies = data.prevention?.strategies || []
  const shiftOf = (key) => {
    const s = strategies.find(x => x.strategy === key)
    return s ? (parseFloat(s.threshold_shift) || 0) : 0
  }
  // 偏移量 = (threshold_shift / 步长) × 平均韧性下降量
  const buildCurve = (shift) => {
    if (shift <= 0) return baseline.slice()
    const offset = (shift / magStep) * avgDrop
    return baseline.map(v => Math.min(0.85, v + offset))
  }
  return {
    baseline,
    A: buildCurve(shiftOf('A')),
    B: buildCurve(shiftOf('B')),
    C: buildCurve(shiftOf('C'))
  }
})

const MAGNITUDES = ['M5.0', 'M5.5', 'M6.0', 'M6.5', 'M7.0', 'M7.5']

const TREND_COLORS = {
  baseline: '#5A6B82', A: '#FFB800', B: '#FF3366', C: '#00FF94'
}
const TREND_BG = {
  baseline: 'rgba(90, 107, 130,0.1)', A: 'rgba(255, 184, 0,0.15)',
  B: 'rgba(255, 51, 102,0.15)', C: 'rgba(0, 255, 148,0.15)'
}

const strategyCards = [
  { key: 'baseline', name: 'Baseline 基线', desc: '无干预', shift: '+0.0M', shiftColor: 'var(--av-muted-foreground)', cls: 's-muted' },
  { key: 'A', name: '策略A 加固路段', desc: '加固10条关键路段', shift: '+0.5M', shiftColor: 'var(--state-warning)', cls: 's-yellow' },
  { key: 'B', name: '策略B 增设医疗', desc: '增设3个医疗点', shift: '+0.0M', shiftColor: 'var(--state-orange)', cls: 's-orange' },
  { key: 'C', name: '策略C A+B组合', desc: '加固路段+增设医疗', shift: '+0.5M', shiftColor: 'var(--state-success)', cls: 's-green' }
]

const layerList = [
  { key: 'effect', label: '策略效果' },
  { key: 'road', label: '加固路段' },
  { key: 'facility', label: '新增设施' }
]

// 从 data.prevention.strategies 动态构建策略对比表（医疗/救援/推移/城市状态）
const compareTable = computed(() => {
  const arr = data.prevention?.strategies
  if (!arr) return []
  return arr.map(s => {
    const shiftNum = parseFloat(s.threshold_shift) || 0
    return {
      key: s.strategy,
      name: s.strategy === 'baseline' ? '基线' : s.strategy,
      med: (s.medical_ratio_after * 100).toFixed(1) + '%',
      res: (s.rescue_ratio_after * 100).toFixed(1) + '%',
      shift: shiftNum > 0 ? `+${shiftNum}M` : '0.0',
      city: s.city_collapse_after ? '崩溃' : '正常',
      cityColor: s.city_collapse_after ? 'var(--state-error)' : 'var(--state-success)'
    }
  })
})

// 从 threshold_shift 和 investment 动态计算 ROI
const roiRows = computed(() => {
  const arr = data.prevention?.strategies
  if (!arr) return []
  const strats = STRATEGIES.value
  const rows = arr
    .filter(s => s.strategy !== 'baseline')
    .map(s => {
      const strat = strats[s.strategy] || {}
      const roi = strat.roi || 0
      const meta = STRATEGY_META[s.strategy] || STRATEGY_META.baseline
      return {
        name: meta.name,
        roi,
        val: roi > 0 ? roi.toFixed(1) + 'x' : '0x',
        color: meta.colorVar
      }
    })
  const maxRoi = Math.max(...rows.map(r => r.roi), 0.001)
  return rows.map(r => ({
    name: r.name,
    pct: r.roi > 0 ? Math.round(r.roi / maxRoi * 1000) / 10 : 0,
    val: r.val,
    color: r.color
  }))
})

// 各策略投入概括文案（用于 ROI 面板底部说明，动态读取，避免硬编码）
const roiSummaryText = computed(() => {
  return STRATEGY_LIST
    .filter(k => k !== 'baseline')
    .map(k => {
      const s = STRATEGIES.value[k]
      return s ? `${s.name}: ¥${s.investment}亿${s.thresholdShift > 0 ? '(推移+' + s.thresholdShift + 'M)' : ''}` : ''
    })
    .filter(Boolean)
    .join(' · ')
})

const mapTools = [
  { key: 'zoom-in', icon: ZoomIn, title: '放大' },
  { key: 'zoom-out', icon: ZoomOut, title: '缩小' },
  { key: 'home', icon: Home, title: '复位' },
  { key: 'identify', icon: MousePointerClick, title: '识别' },
  { key: 'ruler', icon: Ruler, title: '测距' },
  { key: 'fullscreen', icon: Maximize, title: '全屏' }
]

// ==================== STATE ====================
const currentStrategy = ref('C')
const layers = reactive({ effect: true, road: true, facility: true, impact: false })

const mapLayers = computed(() => ({
  districts: true,
  roads: layers.road,
  blockedRoads: true,
  hospitals: true,
  rescue: layers.facility,
  shelters: false,
  hazards: false,
  fault: true,
  intensity: layers.effect,
  epicenter: true,
}))
const activeTool = ref('zoom-in')
const tooltip = reactive({
  show: false, x: 0, y: 0, name: '', impLabel: '', impColor: '',
  medBefore: '', medAfter: '', resBefore: '', resAfter: '',
  shift: '', shiftColor: '', collapse: '', collapseColor: ''
})

// ==================== COMPUTED ====================
// 兜底默认策略：当 prevention 数据未加载/加载失败时，避免下游 .length/.toFixed 访问空对象崩溃
const DEFAULT_STRAT = {
  name: '策略C', nameCn: 'A+B组合', desc: '', fullDesc: '', color: 'green', colorVar: 'var(--state-success)',
  icon: ShieldCheck, investment: 0, investmentItems: [],
  medical: 0, rescue: 0, medicalAfter: 0, rescueAfter: 0,
  cityCollapseAfter: false, thresholdShift: 0, roi: 0, score: 0, paybackPeriod: null, recommended: true
}
const currentStrat = computed(() => STRATEGIES.value[currentStrategy.value] || DEFAULT_STRAT)

function kpiColor(after, before) {
  const diff = after - before
  if (diff > 0.1) return 'green'
  if (diff > 0.01) return 'yellow'
  return 'red'
}

const kpiItems = computed(() => {
  const k = data.kpi
  const r = data.charts?.resilience
  if (!k || !r) return []
  return [
    { label: '韧性指数', value: r.resilience_index?.toFixed(3) || 'N/A', color: 'accent' },
    { label: '医疗韧性', value: r.medical?.toFixed(3) || 'N/A', color: 'green' },
    { label: '交通韧性', value: r.transport?.toFixed(3) || 'N/A', color: 'yellow' },
    { label: '避难韧性', value: r.shelter?.toFixed(3) || 'N/A', color: 'green' },
    { label: '安全韧性', value: r.safety?.toFixed(3) || 'N/A', color: 'orange' },
    { label: '当前震级', value: `M${currentMag.value.toFixed(1)}`, color: 'accent' },
    { label: '经济损失', value: `${k.economic_loss_yi?.toFixed(1)}亿`, color: 'red' },
    { label: '崩溃状态', value: k.city_collapse ? '已崩溃' : '未崩溃', color: k.city_collapse ? 'red' : 'green' }
  ]
})

const bannerStyle = computed(() => {
  const s = currentStrat.value
  const styles = {
    green: { iconBg: 'rgba(0, 255, 148,0.15)', iconColor: 'var(--state-success)', borderColor: 'rgba(0, 255, 148,0.3)' },
    yellow: { iconBg: 'rgba(255, 184, 0,0.15)', iconColor: 'var(--state-warning)', borderColor: 'rgba(255, 184, 0,0.3)' },
    orange: { iconBg: 'rgba(255, 51, 102,0.15)', iconColor: 'var(--state-orange)', borderColor: 'rgba(255, 51, 102,0.3)' },
    muted: { iconBg: 'rgba(90, 107, 130,0.15)', iconColor: 'var(--av-muted-foreground)', borderColor: 'var(--av-border)' }
  }
  return styles[s.color]
})

const bannerTitle = computed(() => {
  const s = currentStrat.value
  return s.name + ' · ' + (s.recommended ? '组合最优' : s.nameCn)
})

const investmentRows = computed(() => {
  const s = currentStrat.value
  if (s.investmentItems.length === 0) return null
  return s.investmentItems.map(item => ({
    ...item,
    pct: (item.amount / s.investment * 100).toFixed(1)
  }))
})

const isRoadReinforced = computed(() => currentStrategy.value === 'A' || currentStrategy.value === 'C')
const showMedicalPoints = computed(() => currentStrategy.value === 'B' || currentStrategy.value === 'C')

const roadStyle = computed(() => {
  if (isRoadReinforced.value) return { stroke: '#00FF94', strokeWidth: 2, opacity: 0.9 }
  return { stroke: '#FF4444', strokeWidth: 1.5, opacity: 0.8 }
})

const districtStyles = computed(() => {
  const styles = {}
  for (const d of DISTRICTS) {
    const name = d.name
    if (currentStrategy.value === 'baseline') {
      styles[name] = DISTRICT_ORIGINAL[name]
    } else {
      const imp = DISTRICT_IMPROVEMENT[currentStrategy.value][name] || 0
      if (imp > 0.5) styles[name] = { fill: 'rgba(0, 255, 148,0.15)', stroke: '#00FF94', sw: 0.6 }
      else if (imp > 0.2) styles[name] = { fill: 'rgba(0, 255, 148,0.06)', stroke: '#1E3A5F', sw: 0.5 }
      else if (imp > 0) styles[name] = { fill: 'rgba(90, 107, 130,0.04)', stroke: '#1E3A5F', sw: 0.5 }
      else styles[name] = DISTRICT_ORIGINAL[name]
    }
  }
  return styles
})

function hospitalFill(baseReach) {
  const s = currentStrat.value
  const reach = baseReach * s.medicalAfter / 0.2676
  if (reach < 0.3) return '#FF4444'
  if (reach < 0.6) return '#FFB800'
  return '#00FF94'
}

const threshData = computed(() => {
  const s = currentStrat.value
  const medBeforePct = (s.medical * 100).toFixed(1)
  const medAfterPct = (s.medicalAfter * 100).toFixed(1)
  const resBeforePct = (s.rescue * 100).toFixed(1)
  const resAfterPct = (s.rescueAfter * 100).toFixed(1)
  const medImproveNum = (s.medicalAfter - s.medical) * 100
  const resImproveNum = (s.rescueAfter - s.rescue) * 100
  const shiftText = s.thresholdShift > 0
    ? 'M' + (5.5 + s.thresholdShift).toFixed(1) + ' (+' + s.thresholdShift + 'M)'
    : 'M5.5 (+0.0M)'
  return {
    medBeforePct, medAfterPct, resBeforePct, resAfterPct,
    medImprove: medImproveNum.toFixed(1), medImproveNum,
    resImprove: resImproveNum.toFixed(1), resImproveNum,
    shiftText,
    medAfterColor: s.medicalAfter >= 0.3 ? 'var(--state-success)' : 'var(--state-error)',
    resAfterColor: s.rescueAfter >= 0.3 ? 'var(--state-success)' : 'var(--state-orange)',
    shiftColor: s.thresholdShift > 0 ? 'var(--state-success)' : 'var(--state-error)'
  }
})

const gaugeData = computed(() => {
  const s = currentStrat.value
  const score = s.score
  let color
  if (score >= 0.8) color = '#00FF94'
  else if (score >= 0.65) color = '#FFB800'
  else if (score >= 0.5) color = '#00D9FF'
  else color = '#FF4444'
  const cx = 40, cy = 44, r2 = 32
  const startAngle = Math.PI
  const endAngle = startAngle - score * Math.PI
  const x1 = cx + r2 * Math.cos(startAngle)
  const y1 = cy + r2 * Math.sin(startAngle)
  const xe = cx + r2 * Math.cos(endAngle)
  const ye = cy + r2 * Math.sin(endAngle)
  return {
    score: score.toFixed(2),
    color,
    arcPath: `M${x1.toFixed(1)},${y1.toFixed(1)} A${r2},${r2} 0 0,1 ${xe.toFixed(1)},${ye.toFixed(1)}`
  }
})

// ==================== CHARTS ====================
const trendChartRef = ref(null)
const radarChartRef = ref(null)
let trendChart = null
let radarChart = null

function initTrendChart() {
  if (!trendChartRef.value) return
  trendChart = echarts.init(trendChartRef.value)
  updateTrendChart()
}

function updateTrendChart() {
  if (!trendChart) return
  const key = currentStrategy.value
  const s = STRATEGIES.value[key] || {}
  const trends = RESILIENCE_TRENDS.value
  trendChart.setOption({
    grid: { left: 38, right: 15, top: 28, bottom: 25 },
    legend: {
      top: 0,
      textStyle: { color: '#5A6B82', fontSize: 9 },
      itemWidth: 12, itemHeight: 2
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#0B1018',
      borderColor: '#1B2640',
      textStyle: { color: '#DCE6F0', fontSize: 10 },
      valueFormatter: (v) => v.toFixed(3)
    },
    xAxis: {
      type: 'category',
      data: MAGNITUDES,
      axisLine: { lineStyle: { color: '#1E3A5F' } },
      axisLabel: { color: '#5A6B82', fontSize: 9 },
      axisTick: { show: false }
    },
    yAxis: {
      type: 'value',
      min: 0.35, max: 0.85,
      axisLine: { show: false },
      axisLabel: { color: '#5A6B82', fontSize: 9 },
      splitLine: { lineStyle: { color: '#1E3A5F' } }
    },
    series: [
      {
        name: '基线',
        type: 'line',
        data: trends.baseline || [],
        lineStyle: { color: '#5A6B82', width: 2, type: 'dashed' },
        itemStyle: { color: '#5A6B82' },
        symbolSize: 5,
        markLine: {
          silent: true,
          symbol: 'none',
          data: [
            { xAxis: 'M5.5', lineStyle: { color: '#FF4444', type: 'dashed', width: 1, opacity: 0.5 }, label: { show: false } },
            { xAxis: 'M6.0', lineStyle: { color: '#00FF94', type: 'dashed', width: 1, opacity: 0.5 }, label: { show: false } }
          ]
        }
      },
      {
        name: s.name || key,
        type: 'line',
        data: trends[key] || [],
        lineStyle: { color: TREND_COLORS[key], width: 2 },
        itemStyle: { color: TREND_COLORS[key] },
        symbolSize: 5,
        areaStyle: { color: TREND_BG[key] }
      }
    ]
  }, true)
}

function initRadarChart() {
  if (!radarChartRef.value) return
  radarChart = echarts.init(radarChartRef.value)
  updateRadarChart()
}

function updateRadarChart() {
  if (!radarChart) return
  const key = currentStrategy.value
  const colors = { baseline: '#5A6B82', A: '#FFB800', B: '#FF3366', C: '#00FF94' }
  const bgColors = { baseline: 'rgba(90, 107, 130,0.1)', A: 'rgba(255, 184, 0,0.1)', B: 'rgba(255, 51, 102,0.1)', C: 'rgba(0, 255, 148,0.2)' }
  const names = { baseline: '基线', A: '策略A', B: '策略B', C: '策略C' }
  const chartData = STRATEGY_LIST.map(k => {
    const s = STRATEGIES.value[k] || {}
    const isSelected = k === key
    return {
      value: [
        s.thresholdShift || 0,
        ((s.medicalAfter || 0) - (s.medical || 0)) * 100,
        ((s.rescueAfter || 0) - (s.rescue || 0)) * 100,
        s.roi || 0
      ],
      name: names[k],
      lineStyle: { color: colors[k], width: isSelected ? 2.5 : 1.5 },
      itemStyle: { color: colors[k] },
      areaStyle: { color: bgColors[k] },
      symbol: isSelected ? 'circle' : 'none',
      symbolSize: 4
    }
  })
  radarChart.setOption({
    legend: {
      top: 0,
      textStyle: { color: '#5A6B82', fontSize: 9 },
      itemWidth: 10, itemHeight: 2
    },
    tooltip: {
      backgroundColor: '#0B1018',
      borderColor: '#1B2640',
      textStyle: { color: '#DCE6F0', fontSize: 10 }
    },
    radar: {
      center: ['50%', '58%'],
      radius: '55%',
      indicator: [
        { name: '阈值推移', max: 0.6 },
        { name: '医疗提升(%)', max: 20 },
        { name: '救援提升(%)', max: 16 },
        { name: '投资效率(ROI)', max: 5 }
      ],
      axisName: { color: '#5A6B82', fontSize: 9 },
      splitLine: { lineStyle: { color: '#1E3A5F' } },
      splitArea: { areaStyle: { color: ['rgba(30,58,95,0.03)', 'rgba(30,58,95,0.08)'] } },
      axisLine: { lineStyle: { color: '#1E3A5F' } }
    },
    series: [{ type: 'radar', data: chartData }]
  }, true)
}

function handleResize() {
  trendChart && trendChart.resize()
  radarChart && radarChart.resize()
}

// ==================== METHODS ====================
function selectStrategy(key) {
  currentStrategy.value = key
}

function toggleLayer(layer) {
  layers[layer] = !layers[layer]
}

function showDistrictTooltip(e, name) {
  const s = currentStrat.value
  const imp = DISTRICT_IMPROVEMENT[currentStrategy.value][name] || 0
  let impLabel = '无改善', impColor = 'var(--av-muted-foreground)'
  if (imp > 0.5) { impLabel = '高改善'; impColor = 'var(--state-success)' }
  else if (imp > 0.2) { impLabel = '中改善'; impColor = 'var(--state-warning)' }
  else if (imp > 0) { impLabel = '低改善'; impColor = 'var(--state-orange)' }
  const mapEl = e.currentTarget.closest('.map-container')
  const rect = mapEl.getBoundingClientRect()
  tooltip.x = e.clientX - rect.left + 15
  tooltip.y = e.clientY - rect.top + 15
  tooltip.name = name
  tooltip.impLabel = impLabel
  tooltip.impColor = impColor
  tooltip.medBefore = (s.medical * 100).toFixed(1) + '%'
  tooltip.medAfter = (s.medicalAfter * 100).toFixed(1) + '%'
  tooltip.resBefore = (s.rescue * 100).toFixed(1) + '%'
  tooltip.resAfter = (s.rescueAfter * 100).toFixed(1) + '%'
  tooltip.shift = '+' + s.thresholdShift + 'M'
  tooltip.shiftColor = s.thresholdShift > 0 ? 'var(--state-success)' : 'var(--state-error)'
  tooltip.collapse = s.cityCollapseAfter ? '崩溃' : '正常'
  tooltip.collapseColor = s.cityCollapseAfter ? 'var(--state-error)' : 'var(--state-success)'
  tooltip.show = true
}

function moveDistrictTooltip(e) {
  const mapEl = e.currentTarget.closest('.map-container')
  const rect = mapEl.getBoundingClientRect()
  tooltip.x = e.clientX - rect.left + 15
  tooltip.y = e.clientY - rect.top + 15
}

function hideDistrictTooltip() {
  tooltip.show = false
}

// ==================== LIFECYCLE ====================
onMounted(() => {
  loadDecision()
  nextTick(() => {
    initTrendChart()
    initRadarChart()
    renderDecisionChart()
  })
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  trendChart && trendChart.dispose()
  radarChart && radarChart.dispose()
  trendChart = null
  radarChart = null
})

watch(currentStrategy, () => {
  updateTrendChart()
  updateRadarChart()
})

// 切换震级时，图表数据（来自 data.charts）可能变化，显式刷新两图（避免依赖 data.prevention 恰好同时变更）
watch(currentMag, () => {
  updateTrendChart()
  updateRadarChart()
})

// 当 JSON 数据加载完成时更新图表
// 注意：若首次挂载时 loading 遮罩挡住了图表容器（ref 为 null），需要在此补一次初始化
watch(() => data.prevention, () => {
  nextTick(() => {
    if (!trendChart && trendChartRef.value) initTrendChart()
    if (!radarChart && radarChartRef.value) initRadarChart()
    updateTrendChart()
    updateRadarChart()
  })
}, { deep: true })
</script>

<template>
  <div class="mode-root">
  <!-- Loading -->
  <div v-if="loading && !data.kpi" class="loading-overlay">
    <Loader2 :size="24" class="spin" />
    <span style="margin-left:8px;font-size:12px;color:var(--av-muted-foreground);">加载韧性数据...</span>
  </div>

  <template v-else>
  <!-- ========== KPI Bar ========== -->
  <div class="kpi-bar">
    <div v-for="(item, i) in kpiItems" :key="i" class="kpi-cell">
      <div class="kpi-label">{{ item.label }}</div>
      <div class="kpi-value" :class="item.color">{{ item.value }}</div>
    </div>
  </div>

  <!-- ========== 决策舱：预算 → 底线推移（精致主卡） ========== -->
  <div v-if="currentDecision" class="cockpit-card">
    <!-- 头部 -->
    <div class="cockpit-header">
      <div class="cockpit-title-group">
        <span class="cockpit-title"><ShieldCheck :size="14" style="vertical-align:-2px;color:var(--state-success);" /> 城市底线决策舱</span>
        <span class="cockpit-subtitle">BUDGET &rarr; BOTTOM LINE · 防灾预算分配决策</span>
      </div>
      <div class="cockpit-badges">
        <span class="cockpit-badge">基线 M{{ currentDecision.baseline.toFixed(1) }}</span>
        <span class="cockpit-badge target" :class="currentDecision.current.shift > 0 ? 'saved' : 'flat'">目标 M{{ currentDecision.current.bottom_line_mag.toFixed(1) }}</span>
        <span class="cockpit-badge note">级联口径</span>
      </div>
    </div>
    <!-- 主体 -->
    <div class="cockpit-main">
      <!-- 左：预算控制 -->
      <div class="cockpit-control">
        <div class="cockpit-control-label">防灾预算</div>
        <div class="cockpit-budget-num num">{{ budgetSlider.toFixed(1) }}<span class="unit">亿元</span></div>
        <input v-model.number="budgetSlider" type="range" min="0" max="10" step="0.5" class="cockpit-range" />
        <div class="cockpit-scale"><span>0</span><span>2 亿 · 推高 0.5 级</span><span>10 亿</span></div>
        <div class="cockpit-reco">
          <span class="reco-label">推荐组合</span>
          <span class="reco-pill">加固 {{ currentDecision.current.roads }} 条路段</span>
          <span class="reco-pill dim">+{{ currentDecision.current.med_points }} 医疗点</span>
        </div>
      </div>
      <!-- 中：底线推移曲线 -->
      <div class="cockpit-chart">
        <div ref="decisionChartRef" style="width:100%;height:170px;"></div>
      </div>
      <!-- 右：效果指标 -->
      <div class="cockpit-effects">
        <div class="effect-grid">
          <div class="effect-cell" :class="{ up: currentDecision.current.shift > 0 }">
            <div class="effect-label">城市底线</div>
            <div class="effect-value num">M{{ currentDecision.current.bottom_line_mag.toFixed(1) }}</div>
            <div class="effect-sub" v-if="currentDecision.current.shift > 0">基线 +{{ currentDecision.current.shift.toFixed(1) }}</div>
            <div class="effect-sub" v-else>= 基线</div>
          </div>
          <div class="effect-cell">
            <div class="effect-label">医疗功能率</div>
            <div class="effect-value num accent">+{{ (currentDecision.current.gain_medical * 100).toFixed(1) }}%</div>
            <div class="effect-sub">M6.5 场景</div>
          </div>
          <div class="effect-cell">
            <div class="effect-label">救援功能率</div>
            <div class="effect-value num info">+{{ (currentDecision.current.gain_rescue * 100).toFixed(1) }}%</div>
            <div class="effect-sub">M6.5 场景</div>
          </div>
          <div class="effect-cell">
            <div class="effect-label">边际收益</div>
            <div class="effect-value num warn" style="font-size:11px;">{{ currentDecision.next ? `再+${(currentDecision.next.budget - currentDecision.current.budget).toFixed(1)}亿→M${currentDecision.next.bottom_line_mag.toFixed(1)}` : '已封顶' }}</div>
            <div class="effect-sub">{{ currentDecision.next ? '可继续推高' : '加固 10 路段后递减' }}</div>
          </div>
        </div>
        <div class="cockpit-conclusion">
          <TrendingUp :size="13" style="vertical-align:-2px;flex-shrink:0;" />
          <span><b>{{ budgetSlider.toFixed(1) }} 亿元</b>（加固 {{ currentDecision.current.roads }} 条路段）→ 底线 <b>M{{ currentDecision.baseline.toFixed(1) }}</b> 推至 <b class="hl">M{{ currentDecision.current.bottom_line_mag.toFixed(1) }}</b>，{{ currentDecision.current.shift > 0 ? `每亿元买来 ${(currentDecision.current.shift / Math.max(budgetSlider, 0.1)).toFixed(2)} 级底线高度` : '建议增至 2 亿元' }}</span>
        </div>
      </div>
    </div>
  </div>
  <!-- ========== Three Columns ========== -->
  <div class="three-col">

    <!-- === Left: Strategy Control === -->
    <div class="col-panel">
      <!-- Strategy Banner -->
      <div class="status-banner" :style="{ borderColor: bannerStyle.borderColor }">
        <div class="status-banner-icon" :style="{ background: bannerStyle.iconBg }">
          <component :is="currentStrat.icon" :size="16" :style="{ color: bannerStyle.iconColor }" />
        </div>
        <div class="status-banner-text">
          <div class="status-banner-title">{{ bannerTitle }}</div>
          <div class="status-banner-desc">{{ currentStrat.fullDesc }}</div>
        </div>
      </div>

      <!-- Strategy Selector -->
      <div class="section-label">策略选择</div>
      <div
        v-for="card in strategyCards"
        :key="card.key"
        class="strat-card"
        :class="[card.cls, { active: currentStrategy === card.key }]"
        @click="selectStrategy(card.key)"
      >
        <div class="strat-card-name">{{ card.name }}</div>
        <div class="strat-card-desc">{{ card.desc }}</div>
        <div class="strat-card-shift" :style="{ color: card.shiftColor }">{{ card.shift }}</div>
      </div>

      <!-- Investment Details -->
      <div class="section-label">投资明细</div>
      <div v-if="investmentRows">
        <div v-for="row in investmentRows" :key="row.label" class="invest-row">
          <span class="invest-label">{{ row.label }}</span>
          <div class="invest-bar-wrap">
            <div class="invest-bar-fill" :style="{ width: row.pct + '%', background: row.color }"></div>
          </div>
          <span class="invest-val" :style="{ color: row.color }">¥{{ row.amount }}亿</span>
        </div>
        <div class="data-row" style="margin-top:4px;border-top:1px solid var(--av-border);padding-top:4px;">
          <span class="data-row-key">总投资</span>
          <span class="data-row-val" :style="{ color: currentStrat.colorVar }">¥{{ currentStrat.investment }}亿</span>
        </div>
      </div>
      <div v-else style="font-size:11px;color:var(--av-muted-foreground);text-align:center;padding:8px;">无投资</div>

      <!-- Layers -->
      <div class="section-label">图层</div>
      <div class="flex flex-col gap-1">
        <div
          v-for="layer in layerList"
          :key="layer.key"
          class="flex items-center gap-2 text-xs cursor-pointer layer-toggle"
          :style="{ padding: '2px 4px', color: layers[layer.key] ? 'var(--av-foreground)' : 'var(--av-muted-foreground)' }"
          @click="toggleLayer(layer.key)"
        >
          <CheckSquare v-if="layers[layer.key]" :size="14" style="color:var(--av-primary);" />
          <Square v-else :size="14" />
          <span>{{ layer.label }}</span>
        </div>
      </div>
    </div>

    <!-- === Center: Map + Charts === -->
    <div class="col-center">
      <!-- Map -->
      <div class="map-container">
        <MapContainer
          :magnitude="currentMag"
          :layers="mapLayers"
          class="map-leaflet"
        />

        <!-- Map Toolbar -->
        <div class="map-toolbar">
          <div class="map-info">点击左侧策略卡片查看效果 · 悬停区县查看对比数据</div>
        </div>

        <!-- Legend -->
        <div class="map-legend">
          <div><span style="color:#00FF94;">━</span>加固路段 <span style="color:#00FF94;">✚</span>新增设施</div>
          <div><span style="color:#00FF94;">●</span>高改善 <span style="color:#FFB800;">●</span>中改善 <span style="color:#5A6B82;">●</span>无改善</div>
          <div><span style="color:#5A6B82;">─</span>断裂带 <span style="color:#FF4444;">◎</span>震中</div>
        </div>

        <!-- District Tooltip -->
        <div v-if="tooltip.show" class="district-tooltip" :style="{ left: tooltip.x + 'px', top: tooltip.y + 'px', display: 'block' }">
          <div style="color:var(--av-primary);font-weight:600;margin-bottom:4px;">{{ tooltip.name }} · <span :style="{ color: tooltip.impColor }">{{ tooltip.impLabel }}</span></div>
          <div style="border-top:1px solid var(--av-border);margin-bottom:4px;"></div>
          <div style="display:flex;justify-content:space-between;color:var(--av-muted-foreground);"><span>医疗(前→后)</span><span style="color:var(--av-foreground);font-family:var(--av-font-mono);">{{ tooltip.medBefore }} → {{ tooltip.medAfter }}</span></div>
          <div style="display:flex;justify-content:space-between;color:var(--av-muted-foreground);"><span>救援(前→后)</span><span style="color:var(--av-foreground);font-family:var(--av-font-mono);">{{ tooltip.resBefore }} → {{ tooltip.resAfter }}</span></div>
          <div style="display:flex;justify-content:space-between;color:var(--av-muted-foreground);"><span>阈值推移</span><span :style="{ color: tooltip.shiftColor, fontFamily: 'var(--av-font-mono)' }">{{ tooltip.shift }}</span></div>
          <div style="display:flex;justify-content:space-between;color:var(--av-muted-foreground);"><span>城市状态</span><span :style="{ color: tooltip.collapseColor, fontFamily: 'var(--av-font-mono)' }">{{ tooltip.collapse }}</span></div>
        </div>
      </div>

      <!-- Bottom Panels -->
      <div class="bottom-panels">
        <!-- Radar Chart -->
        <div class="chart-panel">
          <div class="chart-panel-title">
            <span>策略对比雷达图</span>
            <span style="color:var(--state-success);font-size:10px;">当前: {{ currentStrat.name }}</span>
          </div>
          <div class="chart-body" ref="radarChartRef"></div>
        </div>

        <!-- Resilience Trend Line Chart -->
        <div class="chart-panel">
          <div class="chart-panel-title">
            <span>韧性指数趋势 · 基线 vs {{ currentStrat.name }}</span>
            <span style="color:var(--av-primary);font-size:10px;">→ 阈值推移+{{ currentStrat.thresholdShift }}M</span>
          </div>
          <div class="chart-body" ref="trendChartRef"></div>
        </div>
      </div>
    </div>

    <!-- === Right: Data Panels === -->
    <div class="col-panel">
      <!-- Strategy Comparison Table -->
      <div class="panel-item accent">
        <div class="panel-label">策略对比表</div>
        <table class="mini-table">
          <thead>
          <tr>
            <th>策略</th><th class="num">医疗</th><th class="num">救援</th><th class="num">推移</th><th>城市</th>
          </tr>
          </thead>
          <tbody>
          <tr
            v-for="row in compareTable"
            :key="row.key"
            :class="{ highlight: currentStrategy === row.key }"
          >
            <td>{{ row.name }}</td>
            <td class="num">{{ row.med }}</td>
            <td class="num">{{ row.res }}</td>
            <td class="num">{{ row.shift }}</td>
            <td :style="{ color: row.cityColor }">{{ row.city }}</td>
          </tr>
          </tbody>
        </table>
      </div>

      <!-- ROI Analysis -->
      <div class="panel-item">
        <div class="panel-label">ROI分析</div>
        <div v-for="r in roiRows" :key="r.name" class="roi-row">
          <span class="roi-label">{{ r.name }}</span>
          <div class="roi-bar-wrap">
            <div class="roi-bar-fill" :style="{ width: r.pct + '%', background: r.color }"></div>
          </div>
          <span class="roi-val" :style="{ color: r.color }">{{ r.val }}</span>
        </div>
        <div style="font-size:9px;color:var(--av-muted-foreground);margin-top:4px;border-top:1px solid var(--av-border);padding-top:3px;">
          {{ roiSummaryText }}
        </div>
      </div>

      <!-- Threshold Shift Effect -->
      <div class="panel-item green">
        <div class="panel-label">阈值推移效果</div>
        <div class="data-row">
          <span class="data-row-key">基线崩溃震级</span>
          <span class="data-row-val" style="color:var(--state-error);">M5.5</span>
        </div>
        <div class="data-row">
          <span class="data-row-key">推移后震级</span>
          <span class="data-row-val" :style="{ color: threshData.shiftColor }">{{ threshData.shiftText }}</span>
        </div>

        <div style="margin-top:6px;">
          <!-- Medical -->
          <div class="thresh-row">
            <div class="thresh-row-label">
              <span>医疗功能率</span>
              <span :style="{ color: threshData.medImproveNum > 0 ? 'var(--state-success)' : 'var(--av-muted-foreground)' }">+{{ threshData.medImprove }}%</span>
            </div>
            <div class="thresh-bars">
              <div class="thresh-bar-line">
                <span class="thresh-bar-line-label">前</span>
                <div class="thresh-bar-track">
                  <div class="thresh-bar-fill" :style="{ width: threshData.medBeforePct + '%', background: 'var(--state-error)' }"></div>
                </div>
                <span class="thresh-bar-val" style="color:var(--state-error);">{{ threshData.medBeforePct }}%</span>
              </div>
              <div class="thresh-bar-line">
                <span class="thresh-bar-line-label">后</span>
                <div class="thresh-bar-track">
                  <div class="thresh-bar-fill" :style="{ width: threshData.medAfterPct + '%', background: threshData.medAfterColor }"></div>
                </div>
                <span class="thresh-bar-val" :style="{ color: threshData.medAfterColor }">{{ threshData.medAfterPct }}%</span>
              </div>
            </div>
          </div>

          <!-- Rescue -->
          <div class="thresh-row">
            <div class="thresh-row-label">
              <span>救援功能率</span>
              <span :style="{ color: threshData.resImproveNum > 0 ? 'var(--state-success)' : 'var(--av-muted-foreground)' }">+{{ threshData.resImprove }}%</span>
            </div>
            <div class="thresh-bars">
              <div class="thresh-bar-line">
                <span class="thresh-bar-line-label">前</span>
                <div class="thresh-bar-track">
                  <div class="thresh-bar-fill" :style="{ width: threshData.resBeforePct + '%', background: 'var(--state-orange)' }"></div>
                </div>
                <span class="thresh-bar-val" style="color:var(--state-orange);">{{ threshData.resBeforePct }}%</span>
              </div>
              <div class="thresh-bar-line">
                <span class="thresh-bar-line-label">后</span>
                <div class="thresh-bar-track">
                  <div class="thresh-bar-fill" :style="{ width: threshData.resAfterPct + '%', background: threshData.resAfterColor }"></div>
                </div>
                <span class="thresh-bar-val" :style="{ color: threshData.resAfterColor }">{{ threshData.resAfterPct }}%</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Recommendation -->
      <div class="panel-item green">
        <div class="panel-label">推荐方案</div>
        <div style="flex:1;">
          <div class="data-row"><span class="data-row-key">推荐</span><span class="data-row-val" style="color:var(--state-success);">{{ currentStrat.name }}</span></div>
          <div class="data-row"><span class="data-row-key">投资</span><span class="data-row-val">¥{{ currentStrat.investment }}亿</span></div>
          <div class="data-row"><span class="data-row-key">回收期</span><span class="data-row-val" style="color:var(--state-success);">{{ currentStrat.paybackPeriod ? currentStrat.paybackPeriod + '年' : '—' }}</span></div>
        </div>
        <div style="font-size:9px;color:var(--av-muted-foreground);margin-top:4px;border-top:1px solid var(--av-border);padding-top:3px;">
          {{ currentStrat.nameCn }}，阈值推移+{{ currentStrat.thresholdShift }}M
        </div>
      </div>
    </div>

  </div>
  </template>
  </div>
</template>

<style scoped>
/* ===== 决策舱（精致主卡） ===== */
.cockpit-card {
  background: linear-gradient(180deg, rgba(17, 26, 42,0.85), rgba(17, 26, 42,0.6));
  border: 1px solid var(--av-border);
  border-top: 3px solid var(--state-success);
  border-radius: 16px;
  padding: 16px 20px 14px;
  margin-bottom: 14px;
  box-shadow: 0 6px 24px rgba(0,0,0,0.25);
}
.cockpit-header { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.cockpit-title-group { display: flex; flex-direction: column; }
.cockpit-title { font-size: 15px; font-weight: 700; color: var(--av-foreground); }
.cockpit-subtitle { font-size: 9.5px; letter-spacing: 0.08em; color: var(--av-muted-foreground); }
.cockpit-badges { margin-left: auto; display: flex; gap: 6px; }
.cockpit-badge { display: inline-flex; align-items: center; padding: 3px 10px; border-radius: 999px; font-size: 10px; font-weight: 600; background: var(--av-muted); color: var(--av-muted-foreground); }
.cockpit-badge.target.saved { background: rgba(0, 255, 148,0.14); color: var(--state-success); }
.cockpit-badge.target.flat { background: rgba(255, 68, 68,0.14); color: var(--state-error); }
.cockpit-badge.note { font-size: 9px; background: rgba(0, 217, 255,0.1); color: var(--av-primary); }
.cockpit-main { display: grid; grid-template-columns: minmax(0,0.9fr) minmax(0,1.5fr) minmax(0,1.2fr); gap: 16px; align-items: stretch; }
.cockpit-control { display: flex; flex-direction: column; justify-content: center; gap: 6px; padding: 4px 6px; }
.cockpit-control-label { font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--av-muted-foreground); }
.cockpit-budget-num { font-size: 32px; font-weight: 800; color: var(--av-primary); font-family: var(--av-font-mono); line-height: 1; }
.cockpit-budget-num .unit { font-size: 12px; color: var(--av-muted-foreground); margin-left: 3px; font-weight: 600; }
.cockpit-range { width: 100%; height: 6px; accent-color: var(--state-success); cursor: pointer; }
.cockpit-scale { display: flex; justify-content: space-between; font-size: 8.5px; color: var(--av-muted-foreground); }
.cockpit-reco { display: flex; align-items: center; gap: 6px; margin-top: 2px; }
.reco-label { font-size: 9px; color: var(--av-muted-foreground); }
.reco-pill { font-size: 9.5px; font-weight: 600; color: var(--av-primary); background: rgba(0, 217, 255,0.08); border: 1px solid rgba(0, 217, 255,0.25); border-radius: 4px; padding: 1px 7px; }
.reco-pill.dim { color: var(--av-muted-foreground); background: var(--av-muted); border-color: var(--av-border); }
.cockpit-chart { background: rgba(10,19,32,0.55); border: 1px solid var(--av-border); border-radius: 12px; padding: 6px 8px; }
.cockpit-effects { display: flex; flex-direction: column; gap: 8px; }
.effect-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.effect-cell { background: rgba(10,19,32,0.6); border: 1px solid var(--av-border); border-radius: 10px; padding: 8px 10px; display: flex; flex-direction: column; gap: 2px; }
.effect-cell.up { border-left: 2px solid var(--state-success); }
.effect-label { font-size: 8.5px; color: var(--av-muted-foreground); letter-spacing: 0.05em; }
.effect-value { font-size: 17px; font-weight: 800; font-family: var(--av-font-mono); color: var(--av-foreground); line-height: 1.15; }
.effect-value.accent { color: var(--av-primary); }
.effect-value.info { color: var(--state-info); }
.effect-value.warn { color: var(--state-warning); }
.effect-sub { font-size: 8px; color: var(--av-muted-foreground); }
.cockpit-conclusion { display: flex; align-items: center; gap: 8px; font-size: 10.5px; color: var(--av-foreground); line-height: 1.55; background: linear-gradient(90deg, rgba(0, 255, 148,0.1), rgba(0, 217, 255,0.05)); border-left: 3px solid var(--state-success); border-radius: 4px; padding: 7px 10px; }
.cockpit-conclusion b.hl { color: var(--state-success); }
</style>
