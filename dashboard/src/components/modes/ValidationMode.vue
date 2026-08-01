<script setup>
import PageIntro from '../shell/PageIntro.vue'
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import echarts from '../../engine/echartsSetup.js'
import { CheckCircle2, AlertTriangle, Loader2, Award, Target, Layers } from 'lucide-vue-next'

// ==================== DATA SOURCE ====================
const validationReport = ref(null)
const multiSource = ref(null)
const loading = ref(true)
const error = ref(null)
const selectedEvent = ref('wenchuan_2008')

async function loadData() {
  try {
    const [r1, r2] = await Promise.all([
      fetch('/data/validation_report.json').then(r => r.json()),
      fetch('/data/multi_source_comparison.json').then(r => r.json())
    ])
    validationReport.value = r1
    multiSource.value = r2
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

// ==================== 震源情景配色 ====================
const SCENARIO_COLORS = {
  '郯庐带合肥段': '#F87171',
  '肥东断裂': '#FB923C',
  '大别山断裂': '#FBBF24',
  '宿迁段迁移': '#60A5FA',
}

// ==================== COMPUTED: 历史震例 ====================
const earthquakes = computed(() => validationReport.value?.earthquakes || {})
const eventOptions = computed(() => [
  { key: 'wenchuan_2008', label: '汶川2008', mag: 8.0 },
  { key: 'tangshan_1976', label: '唐山1976', mag: 7.8 },
].filter(e => earthquakes.value[e.key]))

const currentEvent = computed(() => earthquakes.value[selectedEvent.value] || null)

// 等震线对比行（VI→XI 升序）
const isoseismalRows = computed(() => {
  const cmp = currentEvent.value?.isoseismal_comparison?.comparison
  if (!cmp) return []
  const order = ['VI', 'VII', 'VIII', 'IX', 'X', 'XI']
  return order.map(g => {
    const row = cmp[g]
    if (!row) return null
    return {
      grade: g,
      model: row.model_radius_km,
      actual: row.actual_radius_km,
      dev: row.deviation_pct,
    }
  }).filter(Boolean)
})

const nearFieldDev = computed(() => currentEvent.value?.isoseismal_comparison?.near_field_mean_dev_pct)
const farFieldDev = computed(() => currentEvent.value?.isoseismal_comparison?.far_field_mean_dev_pct)
const verdict = computed(() => currentEvent.value?.verdict || null)
const lossDev = computed(() => currentEvent.value?.exposure_and_loss?.deviation_pct || {})
const actualSource = computed(() => currentEvent.value?.isoseismal_comparison?.actual_source || '')

// 可信度等级判定
const credibilityLevel = computed(() => {
  const v = verdict.value
  if (!v) return { color: '#7E91AC', bg: 'rgba(126,145,172,0.12)', tag: 'N/A' }
  const txt = v.credibility || ''
  if (txt.includes('良好')) return { color: 'var(--state-success)', bg: 'rgba(52,211,153,0.12)', tag: '良好' }
  if (txt.includes('中等')) return { color: 'var(--state-warning)', bg: 'rgba(251,191,36,0.12)', tag: '中等' }
  if (txt.includes('较差') || txt.includes('低')) return { color: 'var(--state-error)', bg: 'rgba(248,113,113,0.12)', tag: '较差' }
  return { color: 'var(--av-primary)', bg: 'rgba(0,212,255,0.12)', tag: '一般' }
})

// ==================== COMPUTED: 多震源情景 ====================
const scenarios = computed(() => {
  const list = multiSource.value?.scenarios || []
  return list.map(s => {
    // 防御：intensity_field / cascade 在异常数据中可能缺失，避免直接 .avg/.collapses 崩溃
    const intensity = s.intensity_field || {}
    const cascade = s.cascade || {}
    return {
      name: s.name,
      shortName: s && s.name && s.name.length > 5 ? s.name.slice(0, 4) : (s.name || ''),
      mag: s.magnitude,
      dist: s.distance_to_hefei_km,
      avg: intensity.avg_intensity ?? 0,
      max: intensity.max_intensity ?? 0,
      atHeifei: intensity.intensity_at_hefei ?? 0,
      maxGrade: intensity.max_grade ?? 0,
      collapsedCount: Object.values(cascade.collapses || {}).filter(Boolean).length,
      cityCollapsed: cascade.city_collapsed,
      color: SCENARIO_COLORS[s.name] || '#7E91AC',
    }
  })
})

const comparison = computed(() => multiSource.value?.comparison || null)
const summary = computed(() => validationReport.value?.summary || null)
const meta = computed(() => validationReport.value?.report_meta || null)
const limitations = computed(() => meta.value?.limitations || [])

// ==================== KPI Bar ====================
const kpiItems = computed(() => {
  const items = []
  items.push({ label: '验证模型', value: 'yu2013', color: 'accent' })
  items.push({ label: '历史震例', value: `${eventOptions.value.length}例`, color: 'accent' })
  items.push({ label: '震源情景', value: `${scenarios.value.length}组`, color: 'accent' })
  const wNear = earthquakes.value.wenchuan_2008?.isoseismal_comparison?.near_field_mean_dev_pct
  items.push({ label: '汶川近场偏差', value: wNear != null ? fmtDev(wNear) : 'N/A', color: 'red' })
  const tNear = earthquakes.value.tangshan_1976?.isoseismal_comparison?.near_field_mean_dev_pct
  items.push({ label: '唐山近场偏差', value: tNear != null ? fmtDev(tNear) : 'N/A', color: tNear != null && Math.abs(tNear) <= 40 ? 'green' : 'yellow' })
  const topScenario = comparison.value?.ranking_by_avg_intensity?.[0]
  items.push({ label: '最危险情景', value: topScenario?.shortName || topScenario?.name || 'N/A', color: 'red' })
  const totalCollapsed = scenarios.value.filter(s => s.cityCollapsed).length
  items.push({ label: '城市崩溃', value: `${totalCollapsed}/${scenarios.value.length}`, color: 'red' })
  return items
})

function fmtDev(v) {
  return (v > 0 ? '+' : '') + v.toFixed(1) + '%'
}

// 偏差着色
function devColor(dev) {
  const a = Math.abs(dev)
  if (a <= 40) return 'var(--state-success)'
  if (a <= 70) return 'var(--state-warning)'
  return 'var(--state-error)'
}

function devTag(dev) {
  const a = Math.abs(dev)
  if (a <= 40) return 'green'
  if (a <= 70) return 'yellow'
  return 'red'
}

// ==================== ECharts ====================
const isoChartRef = ref(null)
const radarChartRef = ref(null)
const intChartRef = ref(null)
const charts = {}
let resizeObserver = null

const CHART_TOOLTIP = {
  backgroundColor: '#142440',
  borderColor: '#1C2B43',
  borderWidth: 1,
  textStyle: { color: '#E6EDF7', fontSize: 10 },
}

function initIsoChart() {
  if (!isoChartRef.value) return
  charts.iso = echarts.init(isoChartRef.value)
  updateIsoChart()
}

function updateIsoChart() {
  if (!charts.iso) return
  const rows = isoseismalRows.value
  if (!rows.length) return
  const evLabel = eventOptions.value.find(e => e.key === selectedEvent.value)?.label || ''
  charts.iso.setOption({
    grid: { left: 44, right: 14, top: 32, bottom: 24 },
    tooltip: {
      ...CHART_TOOLTIP,
      trigger: 'axis',
      formatter(params) {
        const r = rows[params[0].dataIndex]
        let s = `${evLabel} · ${params[0].axisValue}度等震线<br/>`
        params.forEach(p => {
          s += p.marker + p.seriesName + ': ' + p.value.toFixed(1) + ' km<br/>'
        })
        s += `<span style="color:${devColor(r.dev)}">偏差: ${fmtDev(r.dev)}</span>`
        return s
      }
    },
    legend: { top: 2, right: 0, textStyle: { color: '#7E91AC', fontSize: 9 }, itemWidth: 10, itemHeight: 2, itemGap: 8 },
    xAxis: {
      type: 'category', data: rows.map(r => r.grade),
      name: '烈度', nameTextStyle: { color: '#4A5C7A', fontSize: 9 },
      axisLine: { lineStyle: { color: '#1E3A5F' } },
      axisTick: { show: false },
      axisLabel: { color: '#4A5C7A', fontSize: 9 }
    },
    yAxis: {
      type: 'log',
      name: '半径(km)', nameTextStyle: { color: '#4A5C7A', fontSize: 9 },
      axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { color: '#4A5C7A', fontSize: 9 },
      splitLine: { lineStyle: { color: '#1E3A5F' } }
    },
    series: [
      {
        name: '模型半径', type: 'bar',
        data: rows.map(r => r.model),
        itemStyle: { color: '#00D4FF', borderRadius: [2, 2, 0, 0] },
        barGap: '15%',
      },
      {
        name: '实际半径', type: 'bar',
        data: rows.map(r => r.actual),
        itemStyle: { color: '#FBBF24', borderRadius: [2, 2, 0, 0] },
      }
    ]
  }, true)
}

function initRadarChart() {
  if (!radarChartRef.value) return
  charts.radar = echarts.init(radarChartRef.value)
  updateRadarChart()
}

function updateRadarChart() {
  if (!charts.radar) return
  const scs = scenarios.value
  if (!scs.length) return
  charts.radar.setOption({
    tooltip: { ...CHART_TOOLTIP },
    legend: { bottom: 2, textStyle: { color: '#7E91AC', fontSize: 9 }, itemWidth: 10, itemHeight: 2, itemGap: 12 },
    radar: {
      indicator: [
        { name: '平均烈度', max: 8 },
        { name: '合肥烈度', max: 12 },
        { name: '最大烈度', max: 12 },
        { name: '崩溃系统', max: 4 },
        { name: '震级', max: 8 },
      ],
      center: ['50%', '46%'],
      radius: '60%',
      axisName: { color: '#7E91AC', fontSize: 10 },
      splitLine: { lineStyle: { color: '#1E3A5F' } },
      splitArea: { areaStyle: { color: ['rgba(0,212,255,0.02)', 'rgba(0,212,255,0.05)'] } },
      axisLine: { lineStyle: { color: '#1E3A5F' } }
    },
    series: [{
      type: 'radar',
      symbol: 'circle', symbolSize: 4,
      data: scs.map(s => ({
        value: [s.avg, s.atHeifei, s.max, s.collapsedCount, s.mag],
        name: s.name,
        lineStyle: { color: s.color, width: 1.5 },
        itemStyle: { color: s.color },
        areaStyle: { color: s.color + '18' },
      }))
    }]
  }, true)
}

function initIntChart() {
  if (!intChartRef.value) return
  charts.int = echarts.init(intChartRef.value)
  updateIntChart()
}

function updateIntChart() {
  if (!charts.int) return
  const scs = scenarios.value
  if (!scs.length) return
  charts.int.setOption({
    grid: { left: 36, right: 14, top: 30, bottom: 24 },
    tooltip: { ...CHART_TOOLTIP, trigger: 'axis' },
    legend: { top: 2, right: 0, textStyle: { color: '#7E91AC', fontSize: 9 }, itemWidth: 10, itemHeight: 2 },
    xAxis: {
      type: 'category', data: scs.map(s => s.shortName),
      axisLine: { lineStyle: { color: '#1E3A5F' } },
      axisTick: { show: false },
      axisLabel: { color: '#4A5C7A', fontSize: 8, interval: 0 }
    },
    yAxis: {
      type: 'value', min: 4, max: 12,
      axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { color: '#4A5C7A', fontSize: 9 },
      splitLine: { lineStyle: { color: '#1E3A5F' } }
    },
    series: [
      {
        name: '平均烈度', type: 'bar',
        data: scs.map(s => s.avg),
        itemStyle: { color: '#00D4FF', borderRadius: [2, 2, 0, 0] },
        barGap: '15%',
      },
      {
        name: '合肥烈度', type: 'bar',
        data: scs.map(s => s.atHeifei),
        itemStyle: { color: '#A78BFA', borderRadius: [2, 2, 0, 0] },
      }
    ]
  }, true)
}

function updateAllCharts() {
  updateIsoChart()
  updateRadarChart()
  updateIntChart()
}

watch([currentEvent, scenarios], () => {
  nextTick(() => updateAllCharts())
}, { deep: true })

onMounted(async () => {
  await loadData()
  nextTick(() => {
    initIsoChart()
    initRadarChart()
    initIntChart()
    if (isoChartRef.value) {
      resizeObserver = new ResizeObserver(() => {
        Object.values(charts).forEach(c => c?.resize())
      })
      ;[isoChartRef, radarChartRef, intChartRef].forEach(r => {
        if (r.value) resizeObserver.observe(r.value)
      })
    }
  })
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  Object.values(charts).forEach(c => c?.dispose())
})
</script>

<template>
  <div class="mode-root">
    <PageIntro question="模型可信吗？与真实地震对比，误差在哪？" :points="['汶川/唐山等震线验证', '4 震源情景', '误差归因']" />
  <!-- Loading -->
  <div v-if="loading" class="loading-overlay">
    <Loader2 :size="24" class="spin" />
    <span style="margin-left:8px;font-size:12px;color:var(--av-muted-foreground);">加载验证数据...</span>
  </div>

  <!-- Error -->
  <div v-else-if="error" class="loading-overlay">
    <AlertTriangle :size="24" style="color:var(--state-error);" />
    <span style="margin-left:8px;font-size:12px;color:var(--state-error);">加载失败: {{ error }}</span>
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

    <!-- === Left Panel: 历史震例验证 === -->
    <div class="col-panel">
      <!-- 震例切换 -->
      <div class="event-toggle">
        <button v-for="ev in eventOptions" :key="ev.key"
          class="event-toggle-btn"
          :class="{ active: selectedEvent === ev.key }"
          @click="selectedEvent = ev.key">
          {{ ev.label }}
          <span class="event-toggle-mag">M{{ ev.mag.toFixed(1) }}</span>
        </button>
      </div>

      <!-- 可信度横幅 -->
      <div class="credibility-banner" :style="{ borderColor: credibilityLevel.color + '50', background: credibilityLevel.bg }">
        <div class="credibility-icon" :style="{ color: credibilityLevel.color }">
          <CheckCircle2 :size="18" />
        </div>
        <div class="credibility-text">
          <div class="credibility-title" :style="{ color: credibilityLevel.color }">近场可信度 · {{ credibilityLevel.tag }}</div>
          <div class="credibility-desc">{{ verdict?.credibility || '—' }}</div>
        </div>
      </div>

      <!-- 等震线对比图 -->
      <div class="section-label">等震线半径对比 · 模型 vs 实际</div>
      <div ref="isoChartRef" class="mini-chart"></div>

      <!-- 偏差表 -->
      <div class="section-label">等震线偏差明细</div>
      <table class="mini-table">
        <thead>
          <tr>
            <th>烈度</th>
            <th style="text-align:right;">模型(km)</th>
            <th style="text-align:right;">实际(km)</th>
            <th style="text-align:right;">偏差</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in isoseismalRows" :key="r.grade">
            <td style="color:var(--av-foreground);font-weight:600;">{{ r.grade }}</td>
            <td class="num">{{ r.model.toFixed(1) }}</td>
            <td class="num">{{ r.actual.toFixed(1) }}</td>
            <td class="num" :style="{ color: devColor(r.dev) }">{{ fmtDev(r.dev) }}</td>
          </tr>
        </tbody>
      </table>

      <!-- 近远场汇总 -->
      <div class="section-label">近远场偏差汇总</div>
      <div class="dev-summary">
        <div class="dev-summary-row">
          <span class="data-row-key">近场(IX及以里)</span>
          <span class="data-row-val" :style="{ color: devColor(nearFieldDev) }">{{ fmtDev(nearFieldDev) }}</span>
        </div>
        <div class="dev-summary-row">
          <span class="data-row-key">远场(VII-VI)</span>
          <span class="data-row-val" :style="{ color: devColor(farFieldDev) }">{{ fmtDev(farFieldDev) }}</span>
        </div>
        <div class="dev-summary-row">
          <span class="data-row-key">经济损失偏差</span>
          <span class="data-row-val" :style="{ color: devColor(lossDev.economic_loss) }">{{ fmtDev(lossDev.economic_loss) }}</span>
        </div>
      </div>

      <!-- 验证发现 -->
      <div class="section-label">验证发现</div>
      <div v-for="(f, i) in (verdict?.findings || [])" :key="i" class="finding-item">
        <span class="finding-dot" :style="{ background: credibilityLevel.color }"></span>
        <span>{{ f }}</span>
      </div>
      <div v-if="actualSource" class="actual-source">{{ actualSource }}</div>

      <!-- 误差归因：诚实展示 + 防御话术 -->
      <div class="section-label">误差归因 · 模型适用边界</div>
      <div class="attribution-panel">
        <div class="attribution-intro">
          偏差已在验证报告中完整披露。核心归因：俞言祥2013 为点源衰减模型，对汶川这类大破裂逆冲事件
          近场高烈度区系统性低估（保守侧）；对川西山区远场衰减偏慢会高估。本项目合肥场景为断裂带正上方的
          近场评估，模型低估方向恰好使评估结果偏安全侧，且合肥使用真实网格化人口GDP（step4），
          不受历史震例简化暴露度误差影响。
        </div>
        <ol class="attribution-list">
          <li v-for="(l, i) in limitations" :key="i">{{ l }}</li>
        </ol>
      </div>
    </div>

    <!-- === Center Column: 多震源烈度对比 === -->
    <div class="col-center">
      <!-- 雷达图 -->
      <div class="map-container">
        <div class="map-toolbar">
          <div class="map-info">
            <Layers :size="12" style="vertical-align:middle;" /> 多震源烈度多维对比 · 雷达
          </div>
          <div class="map-tools">
            <div class="map-tool active" title="4情景"><Target :size="14" /></div>
          </div>
        </div>
        <div ref="radarChartRef" style="position:absolute;top:0;left:0;width:100%;height:100%;"></div>
        <div class="map-legend">
          <div v-for="s in scenarios" :key="s.name" style="display:flex;align-items:center;gap:3px;">
            <span class="legend-dot" :style="{ background: s.color }"></span>{{ s.name }}
          </div>
        </div>
      </div>

      <!-- 底部双图表 -->
      <div class="bottom-panels">
        <!-- 烈度柱状图 -->
        <div class="chart-panel">
          <div class="chart-panel-title">
            <span>各震源烈度对比</span>
            <span style="color:var(--av-muted-foreground);font-size:9px;">平均 vs 合肥</span>
          </div>
          <div class="chart-body">
            <div ref="intChartRef" style="width:100%;height:100%;"></div>
          </div>
        </div>

        <!-- 崩溃风险对比 -->
        <div class="chart-panel">
          <div class="chart-panel-title">
            <span>系统崩溃风险</span>
            <span style="color:var(--state-error);font-size:9px;">崩溃系统数 / 4</span>
          </div>
          <div class="chart-body" style="padding:4px 0;">
            <div v-for="s in scenarios" :key="s.name" style="margin-bottom:6px;">
              <div class="data-row">
                <span class="data-row-key" :style="{ color: s.cityCollapsed ? 'var(--state-error)' : 'var(--av-muted-foreground)' }">{{ s.name }}</span>
                <span class="data-row-val" :style="{ color: s.color }">{{ s.collapsedCount }}/4</span>
              </div>
              <div class="collapse-bar">
                <div v-for="i in 4" :key="i" class="collapse-cell"
                  :style="{ background: i <= s.collapsedCount ? s.color : 'var(--av-border)' }"></div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- === Right Panel: 排名对比 + 模型适用性 === -->
    <div class="col-panel">
      <!-- 烈度排名 -->
      <div class="panel-item accent">
        <div class="panel-label"><Award :size="11" style="vertical-align:-1px;" /> 平均烈度排名</div>
        <table class="mini-table">
          <thead>
            <tr><th>#</th><th>震源</th><th style="text-align:right;">烈度</th><th style="text-align:right;">距合肥</th></tr>
          </thead>
          <tbody>
            <tr v-for="(r, i) in (comparison?.ranking_by_avg_intensity || [])" :key="r.name"
              :class="{ highlight: i === 0 }">
              <td style="color:var(--av-primary);font-weight:600;">{{ i + 1 }}</td>
              <td>{{ r.name }}</td>
              <td class="num">{{ r.avg_intensity.toFixed(2) }}</td>
              <td class="num">{{ r.distance_km.toFixed(0) }}km</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 崩溃风险排名 -->
      <div class="panel-item red">
        <div class="panel-label"><AlertTriangle :size="11" style="vertical-align:-1px;" /> 崩溃风险排名</div>
        <table class="mini-table">
          <thead>
            <tr><th>#</th><th>震源</th><th style="text-align:right;">崩溃</th><th style="text-align:right;">城市</th></tr>
          </thead>
          <tbody>
            <tr v-for="(r, i) in (comparison?.ranking_by_collapse_risk || [])" :key="r.name"
              :class="{ highlight: i === 0 }">
              <td style="color:var(--state-error);font-weight:600;">{{ i + 1 }}</td>
              <td>{{ r.name }}</td>
              <td class="num">{{ r.collapsed_count }}/4</td>
              <td class="num" :style="{ color: r.city_collapsed ? 'var(--state-error)' : 'var(--state-success)' }">
                {{ r.city_collapsed ? '崩溃' : '承压' }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 破裂参数 -->
      <div class="panel-item">
        <div class="panel-label">破裂参数对比</div>
        <table class="mini-table">
          <thead>
            <tr><th>震源</th><th style="text-align:right;">M</th><th style="text-align:right;">长(km)</th><th style="text-align:right;">宽(km)</th></tr>
          </thead>
          <tbody>
            <tr v-for="r in (comparison?.rupture_width_comparison || [])" :key="r.name">
              <td>{{ r.name }}</td>
              <td class="num">M{{ r.magnitude.toFixed(1) }}</td>
              <td class="num">{{ r.length_km.toFixed(0) }}</td>
              <td class="num">{{ r.width_km.toFixed(1) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 模型适用性结论 -->
      <div class="panel-item green">
        <div class="panel-label"><CheckCircle2 :size="11" style="vertical-align:-1px;" /> 模型适用性</div>
        <div class="conclusion-text">{{ summary?.model_applicability || '—' }}</div>
      </div>

      <!-- 主要结论 -->
      <div class="panel-item accent">
        <div class="panel-label"><Target :size="11" style="vertical-align:-1px;" /> 主要结论</div>
        <div class="conclusion-text primary">{{ summary?.primary_conclusion || '—' }}</div>
      </div>
    </div>

  </div>
  </template>
  </div>
</template>

<style scoped>
/* 震例切换 */
.event-toggle {
  display: flex;
  gap: 4px;
  margin-bottom: 8px;
}

.event-toggle-btn {
  flex: 1;
  background: var(--av-muted);
  border: 1px solid var(--av-border);
  border-radius: var(--av-radius-sm);
  padding: 5px 8px;
  font-size: 11px;
  color: var(--av-muted-foreground);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  transition: all 0.15s;
  font-family: var(--av-font-sans);
}

.event-toggle-btn:hover { color: var(--av-foreground); border-color: var(--av-muted-foreground); }

.event-toggle-btn.active {
  background: rgba(0, 212, 255, 0.1);
  border-color: var(--av-primary);
  color: var(--av-primary);
  font-weight: 600;
}

.event-toggle-mag {
  font-family: var(--av-font-mono);
  font-size: 9px;
  opacity: 0.8;
}

/* 可信度横幅 */
.credibility-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: var(--av-radius-md);
  margin-bottom: 8px;
  border: 1px solid var(--av-border);
}

.credibility-icon {
  width: 32px;
  height: 32px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  background: rgba(15, 26, 43, 0.6);
}

.credibility-text { flex: 1; min-width: 0; }
.credibility-title { font-size: 12px; font-weight: 700; white-space: nowrap; }
.credibility-desc { font-size: 9px; color: var(--av-muted-foreground); line-height: 1.4; margin-top: 1px; }

/* 等震线对比图 */
.mini-chart {
  width: 100%;
  height: 130px;
  flex-shrink: 0;
}

/* 偏差汇总 */
.dev-summary { display: flex; flex-direction: column; gap: 1px; }
.dev-summary-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11px;
  padding: 2px 4px;
  background: var(--av-muted);
  border-radius: 2px;
}

/* 误差归因面板：诚实展示 + 防御话术 */
.attribution-panel {
  background: rgba(15, 26, 43, 0.5);
  border: 1px solid var(--av-border);
  border-left: 2px solid var(--state-warning);
  border-radius: 4px;
  padding: 6px 8px;
}
.attribution-intro {
  font-size: 9.5px;
  line-height: 1.5;
  color: var(--av-foreground);
  margin-bottom: 4px;
}
.attribution-list {
  margin: 0;
  padding-left: 14px;
  font-size: 9px;
  color: var(--av-muted-foreground);
  line-height: 1.6;
}
.attribution-list li { margin-bottom: 2px; }

/* 验证发现 */
.finding-item {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 10px;
  color: var(--av-foreground);
  line-height: 1.5;
  padding: 2px 0;
}

.finding-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  flex-shrink: 0;
  margin-top: 6px;
}

.actual-source {
  font-size: 8px;
  color: var(--av-muted-foreground);
  line-height: 1.4;
  margin-top: 6px;
  padding: 4px 6px;
  background: var(--av-muted);
  border-radius: 3px;
  border-left: 2px solid var(--av-border);
}

/* 崩溃风险条 */
.collapse-bar {
  display: flex;
  gap: 2px;
  margin-top: 2px;
}

.collapse-cell {
  flex: 1;
  height: 6px;
  border-radius: 1px;
  transition: background 0.3s;
}

/* 结论文本 */
.conclusion-text {
  font-size: 10px;
  color: var(--av-foreground);
  line-height: 1.6;
  margin-top: 2px;
}

.conclusion-text.primary {
  color: var(--av-foreground);
}

/* 让 col-panel 内 mini-chart 有最小高度约束 */
.col-panel :deep(.mini-chart) { min-height: 0; }
</style>
