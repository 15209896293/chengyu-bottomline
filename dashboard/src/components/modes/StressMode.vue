<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { Target, ShieldAlert, TrendingUp, GitBranch, Loader2, AlertTriangle, FileText, Info, AlertTriangle as Warn, Lightbulb, CheckCircle2 } from 'lucide-vue-next'
import KpiBar from '../shell/KpiBar.vue'

// ==================== DATA SOURCE ====================
const report = ref(null)
const vulnerable = ref(null)
const budget = ref(null)
const loading = ref(true)
const error = ref(null)

async function loadData() {
  try {
    const [r, v, b] = await Promise.all([
      fetch(import.meta.env.BASE_URL + 'data/stress_report.json').then(res => res.json()),
      fetch(import.meta.env.BASE_URL + 'data/vulnerable_exposure.json').then(res => res.json()).catch(() => null),
      fetch(import.meta.env.BASE_URL + 'data/budget_optimization.json').then(res => res.json()).catch(() => null),
    ])
    report.value = r
    vulnerable.value = v
    budget.value = b
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

const kpiItems = computed(() => {
  const items = []
  const city = critical.value.city
  items.push({ label: '城市崩溃临界', value: city != null ? `M${city.toFixed(1)}` : '—', color: city != null && city < 6 ? 'red' : 'yellow' })
  items.push({ label: '医疗临界', value: critical.value.medical != null ? `M${critical.value.medical.toFixed(1)}` : '—', color: 'accent' })
  if (varc.value) {
    items.push({ label: '基准损失', value: `${varc.value.deterministic_loss_yi}亿`, color: 'accent', note: `≈GDP ${(varc.value.deterministic_loss_yi / 10109 * 100).toFixed(1)}%` })
    items.push({ label: 'VaR95', value: `${varc.value.var95_yi}亿`, color: 'red', note: '95%置信上限' })
  }
  if (budget.value?.highlights) {
    items.push({ label: '翻转最小预算', value: `${budget.value.highlights.min_budget_for_city_saved_yi}亿`, color: 'green' })
  }
  return items
})

// ---- 分数映射（0-100）与等级 ----
const CITY_MAG_MIN = 5.0, CITY_MAG_MAX = 8.0
function scoreMag(mag) {
  if (mag == null) return 0
  return Math.round(Math.max(0, Math.min(100, (CITY_MAG_MAX - mag) / (CITY_MAG_MAX - CITY_MAG_MIN) * 100)))
}
function scoreLossRatio(pct) {
  // 尾部损失占 GDP 比例越低越安全（0%→100分, 50%→0分）
  return Math.round(Math.max(0, Math.min(100, 100 - pct * 2)))
}
function grade(score) {
  if (score >= 75) return { label: '优秀', type: 'success' }
  if (score >= 60) return { label: '良好', type: 'info' }
  if (score >= 40) return { label: '待提升', type: 'warning' }
  return { label: '危险', type: 'danger' }
}
const BADGE = {
  success: { bg: 'rgba(0, 255, 148,0.12)', color: 'var(--state-success)' },
  info: { bg: 'rgba(96,165,250,0.12)', color: 'var(--state-info)' },
  warning: { bg: 'rgba(255, 184, 0,0.12)', color: 'var(--state-warning)' },
  danger: { bg: 'rgba(255, 68, 68,0.12)', color: 'var(--state-error)' },
}
const GAUGE_COLOR = {
  success: 'var(--state-success)', info: 'var(--state-info)',
  warning: 'var(--state-warning)', danger: 'var(--state-error)',
}

// ---- 卡片 1：逆压测底线 ----
const card1 = computed(() => {
  const c = critical.value
  const mag = c.city ?? null
  const score = scoreMag(mag)
  const g = grade(score)
  const bars = [
    { label: '医疗系统临界', value: c.medical != null ? `M${c.medical.toFixed(1)}` : '—', pct: scoreMag(c.medical) },
    { label: '救援系统临界', value: c.rescue != null ? `M${c.rescue.toFixed(1)}` : '—', pct: scoreMag(c.rescue) },
    { label: '避难系统临界', value: c.shelter != null ? `M${c.shelter.toFixed(1)}` : '—', pct: scoreMag(c.shelter) },
  ]
  const mv = epiScan.value?.most_vulnerable
  const epiTxt = mv ? `最不利破裂位置 ${mv.lon}, ${mv.lat}（质心即最危险段）` : ''
  return { score, grade: g, bars, mag, epiTxt }
})

// ---- 卡片 2：尾部风险 ----
const card2 = computed(() => {
  const v = varc.value
  if (!v) return null
  const gdp = 10109
  const varPct = v.var95_yi / gdp * 100
  const score = scoreLossRatio(varPct)
  const g = grade(score)
  const maxV = v.cvar95_yi || 1
  const bars = [
    { label: '基准损失', value: `${v.deterministic_loss_yi}亿`, pct: Math.round(v.deterministic_loss_yi / maxV * 100) },
    { label: 'VaR95 上限', value: `${v.var95_yi}亿`, pct: Math.round(v.var95_yi / maxV * 100) },
    { label: 'CVaR95 尾部', value: `${v.cvar95_yi}亿`, pct: Math.round(v.cvar95_yi / maxV * 100) },
  ]
  return { score, grade: g, bars, varPct }
})

// ---- 卡片 3：动态传染 ----
const card3 = computed(() => {
  const dc = contagion.value
  if (!dc) return null
  const hl = dc.highlight_magnitude || '5.5'
  const r = dc.by_magnitude[hl]
  const sys = 'shelter'
  const fixed = r.fixed_dependency.systems[sys]
  const dyn = r.dynamic_dependency.systems[sys]
  const fixedLast = fixed[fixed.length - 1]
  const dynLast = dyn[dyn.length - 1]
  const score = Math.round(dynLast * 100) // 时变功能率 = 安全度
  const g = grade(score)
  const extra = r.reinforcement_extra_drop || {}
  const maxDrop = Math.max(...Object.values(extra), 0.001)
  const bars = Object.entries(extra).map(([k, v]) => ({
    label: { medical: '医疗', rescue: '救援', shelter: '避难', transport: '交通' }[k] || k,
    value: `-${(v * 100).toFixed(1)}%`,
    pct: Math.round(v / maxDrop * 100),
  }))
  const fct = r.fixed_dependency.collapse_time_by_system[sys]
  const dct = r.dynamic_dependency.collapse_time_by_system[sys]
  return { score, grade: g, bars, hl, fixedLast, dynLast, fct, dct }
})

// ---- 卡片 4：韧性投资 ----
const card4 = computed(() => {
  const b = budget.value
  if (!b?.highlights) return null
  const minB = b.highlights.min_budget_for_city_saved_yi ?? 5
  const score = Math.round(Math.max(0, Math.min(100, 100 - minB * 8))) // 预算越小越高效
  const g = grade(score)
  const comb = b.highlights.min_budget_combination || {}
  const curve = b.budget_curve || []
  const maxMed = Math.max(...curve.map(c => c.medical_after), 0.001)
  const bars = [
    { label: '城市翻转预算', value: `${minB}亿`, pct: Math.round(minB / 10 * 100) },
    { label: '最优加固路段', value: `${comb.roads ?? 0}条`, pct: Math.round((comb.roads ?? 0) / 10 * 100) },
    { label: '医疗率提升', value: `${(maxMed * 100).toFixed(1)}%`, pct: Math.round(maxMed * 100) },
  ]
  return { score, grade: g, bars }
})

// ---- 综合评分 ----
const overall = computed(() => {
  const scores = [card1.value?.score ?? 0, card2.value?.score ?? 0, card3.value?.score ?? 0, card4.value?.score ?? 0]
  const avg = Math.round(scores.reduce((a, b) => a + b, 0) / Math.max(scores.length, 1))
  const g = grade(avg)
  const rows = [
    { name: '逆压测 · 城市底线', score: card1.value?.score ?? 0, grade: card1.value ? grade(card1.value.score) : grade(0) },
    { name: '尾部风险 · VaR/CVaR', score: card2.value?.score ?? 0, grade: card2.value ? grade(card2.value.score) : grade(0) },
    { name: '动态传染 · 依赖强化', score: card3.value?.score ?? 0, grade: card3.value ? grade(card3.value.score) : grade(0) },
    { name: '韧性投资 · 预算效率', score: card4.value?.score ?? 0, grade: card4.value ? grade(card4.value.score) : grade(0) },
  ]
  return { avg, grade: g, rows }
})

// ---- 建议（来自数据） ----
const recs = computed(() => {
  const list = []
  if (card1.value?.mag != null) {
    list.push({ icon: Warn, color: card1.value.grade.type === 'success' ? 'var(--state-warning)' : 'var(--state-error)', text: `城市崩溃临界 M${card1.value.mag.toFixed(1)}——救援系统最先失守（M${critical.value.rescue != null ? critical.value.rescue.toFixed(1) : '—'}），路网是底线的第一道闸` })
  }
  if (card2.value) {
    list.push({ icon: ShieldAlert, color: 'var(--state-warning)', text: `尾部风险显著：95% 置信下损失上限 ${card2.value.bars[1].value}，风险准备金目标应不低于 CVaR95 ${card2.value.bars[2].value}` })
  }
  if (budget.value?.highlights) {
    list.push({ icon: TrendingUp, color: 'var(--state-success)', text: `仅需 ${budget.value.highlights.min_budget_for_city_saved_yi} 亿元（加固 ${budget.value.highlights.min_budget_combination?.roads ?? 0} 条关键路段）即可使城市崩溃翻转——加固路段的收益约为医疗点的 10 倍` })
  }
  const kg = vulnerable.value?.by_type?.find(t => t.type === '幼儿园')
  if (kg) {
    list.push({ icon: Lightbulb, color: 'var(--state-info)', text: `脆弱群体承灾：M6.0 下幼儿园 ${(kg.exposure_ratio * 100).toFixed(0)}% 位于高烈度区——防灾规划应优先保障学校/养老院周边的路网韧性` })
  }
  return list
})

// ==================== 导出诊断单 ====================
function exportDiagnosis() {
  if (!report.value) return
  const lines = []
  lines.push('【城域底线 · 压测诊断单】')
  lines.push('='.repeat(32))
  const c = critical.value
  lines.push(`· 城市崩溃临界: M${c.city != null ? c.city.toFixed(1) : '—'} | 医疗 M${c.medical != null ? c.medical.toFixed(1) : '—'} | 救援 M${c.rescue != null ? c.rescue.toFixed(1) : '—'} | 避难 M${c.shelter != null ? c.shelter.toFixed(1) : '—'}`)
  if (varc.value) {
    lines.push(`· 尾部风险: 基准 ${varc.value.deterministic_loss_yi}亿 | VaR95 ${varc.value.var95_yi}亿 | CVaR95 ${varc.value.cvar95_yi}亿`)
  }
  if (budget.value?.highlights) {
    lines.push(`· 韧性投资: ${budget.value.highlights.min_budget_for_city_saved_yi} 亿预算即可翻转城市崩溃`)
  }
  if (overall.value) {
    lines.push(`· 综合压测评分: ${overall.value.avg}（${overall.value.grade.label}）`)
  }
  lines.push('='.repeat(32))
  lines.push('城域底线 · 大数据压测诊断系统')
  const text = lines.join('\n')
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text).then(() => { copied.value = true; setTimeout(() => copied.value = false, 1500) })
  } else {
    const ta = document.createElement('textarea')
    ta.value = text; document.body.appendChild(ta); ta.select()
    document.execCommand('copy'); document.body.removeChild(ta)
    copied.value = true; setTimeout(() => copied.value = false, 1500)
  }
}
const copied = ref(false)

// ==================== 生命周期 ====================
onMounted(loadData)
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
      <div class="export-bar">
        <button class="export-btn" @click="exportDiagnosis">
          <FileText :size="11" style="vertical-align:-1px;" /> {{ copied ? '已复制 ✓' : '导出诊断单' }}
        </button>
        <span class="export-hint">复制政府汇报用压测结论</span>
      </div>

      <!-- ===== 2x2 分析卡片 ===== -->
      <section class="analysis-cards">
        <!-- 卡片1：逆压测 -->
        <div class="analysis-card">
          <div class="card-head">
            <div class="gauge-wrap">
              <svg viewBox="0 0 48 48" class="gauge-ring">
                <circle cx="24" cy="24" r="20" fill="none" stroke="var(--av-border)" stroke-width="4" />
                <circle cx="24" cy="24" r="20" fill="none" :stroke="GAUGE_COLOR[card1.grade.type]" stroke-width="4" stroke-linecap="round"
                        stroke-dasharray="125.6" :stroke-dashoffset="125.6 * (1 - card1.score / 100)" />
              </svg>
              <div class="gauge-center"><span class="num">{{ card1.score }}</span></div>
            </div>
            <div class="card-title">
              <span class="card-zh">逆压测 · 城市底线</span>
              <span class="card-en">REVERSE STRESS TEST</span>
            </div>
            <span class="badge" :style="{ background: BADGE[card1.grade.type].bg, color: BADGE[card1.grade.type].color }">
              {{ card1.grade.label }}<span class="badge-en">/ {{ card1.mag != null ? 'M' + card1.mag.toFixed(1) : '—' }}</span>
            </span>
          </div>
          <div class="metric-list">
            <div v-for="b in card1.bars" :key="b.label" class="metric-row">
              <div class="metric-label"><span>{{ b.label }}</span><span class="num">{{ b.value }}</span></div>
              <div class="progress-track"><div class="progress-fill" :style="{ width: b.pct + '%' }"></div></div>
            </div>
          </div>
          <div class="card-summary">{{ card1.epiTxt }}</div>
          <div class="card-reco">城市底线由救援系统最先触发——路网是防灾的第一道闸</div>
        </div>

        <!-- 卡片2：尾部风险 -->
        <div class="analysis-card" v-if="card2">
          <div class="card-head">
            <div class="gauge-wrap">
              <svg viewBox="0 0 48 48" class="gauge-ring">
                <circle cx="24" cy="24" r="20" fill="none" stroke="var(--av-border)" stroke-width="4" />
                <circle cx="24" cy="24" r="20" fill="none" :stroke="GAUGE_COLOR[card2.grade.type]" stroke-width="4" stroke-linecap="round"
                        stroke-dasharray="125.6" :stroke-dashoffset="125.6 * (1 - card2.score / 100)" />
              </svg>
              <div class="gauge-center"><span class="num">{{ card2.score }}</span></div>
            </div>
            <div class="card-title">
              <span class="card-zh">尾部风险 · VaR/CVaR</span>
              <span class="card-en">TAIL RISK</span>
            </div>
            <span class="badge" :style="{ background: BADGE[card2.grade.type].bg, color: BADGE[card2.grade.type].color }">
              {{ card2.grade.label }}<span class="badge-en">/ VaR95 {{ card2.varPct.toFixed(1) }}% GDP</span>
            </span>
          </div>
          <div class="metric-list">
            <div v-for="b in card2.bars" :key="b.label" class="metric-row">
              <div class="metric-label"><span>{{ b.label }}</span><span class="num">{{ b.value }}</span></div>
              <div class="progress-track"><div class="progress-fill" :class="b.pct > 75 ? 'danger' : 'info'" :style="{ width: b.pct + '%' }"></div></div>
            </div>
          </div>
          <div class="card-summary">参数扰动下尾部损失显著放大（阶梯损失率的阈值效应）</div>
          <div class="card-reco">风险准备金目标 = CVaR95（{{ card2.bars[2].value }}），为巨灾保险定价参考</div>
        </div>

        <!-- 卡片3：动态传染 -->
        <div class="analysis-card" v-if="card3">
          <div class="card-head">
            <div class="gauge-wrap">
              <svg viewBox="0 0 48 48" class="gauge-ring">
                <circle cx="24" cy="24" r="20" fill="none" stroke="var(--av-border)" stroke-width="4" />
                <circle cx="24" cy="24" r="20" fill="none" :stroke="GAUGE_COLOR[card3.grade.type]" stroke-width="4" stroke-linecap="round"
                        stroke-dasharray="125.6" :stroke-dashoffset="125.6 * (1 - card3.score / 100)" />
              </svg>
              <div class="gauge-center"><span class="num">{{ card3.score }}</span></div>
            </div>
            <div class="card-title">
              <span class="card-zh">动态传染 · 依赖强化</span>
              <span class="card-en">CONTAGION · M{{ card3.hl }}</span>
            </div>
            <span class="badge" :style="{ background: BADGE[card3.grade.type].bg, color: BADGE[card3.grade.type].color }">
              {{ card3.grade.label }}<span class="badge-en">/ 避难 T+72h</span>
            </span>
          </div>
          <div class="metric-list">
            <div v-for="b in card3.bars" :key="b.label" class="metric-row">
              <div class="metric-label"><span>{{ b.label }}依赖强化</span><span class="num danger-text">{{ b.value }}</span></div>
              <div class="progress-track"><div class="progress-fill danger" :style="{ width: b.pct + '%' }"></div></div>
            </div>
          </div>
          <div class="card-summary">
            避难系统：固定依赖 {{ (card3.fixedLast * 100).toFixed(1) }}% → 时变依赖 {{ (card3.dynLast * 100).toFixed(1) }}%
            {{ card3.fct != null ? '（固定 ' + (card3.fct == 0 ? 'T+0' : 'T+' + card3.fct + 'h') + ' 失守' : '（固定 72h 未失守' }}
            {{ card3.dct != null ? ' → 时变 ' + (card3.dct == 0 ? 'T+0' : 'T+' + card3.dct + 'h') + ' 失守）' : ' → 时变 72h 未失守）' }}
          </div>
          <div class="card-reco">依赖强化使系统比静态评估更早失守——静态评估会高估城市韧性</div>
        </div>

        <!-- 卡片4：韧性投资 -->
        <div class="analysis-card" v-if="card4">
          <div class="card-head">
            <div class="gauge-wrap">
              <svg viewBox="0 0 48 48" class="gauge-ring">
                <circle cx="24" cy="24" r="20" fill="none" stroke="var(--av-border)" stroke-width="4" />
                <circle cx="24" cy="24" r="20" fill="none" :stroke="GAUGE_COLOR[card4.grade.type]" stroke-width="4" stroke-linecap="round"
                        stroke-dasharray="125.6" :stroke-dashoffset="125.6 * (1 - card4.score / 100)" />
              </svg>
              <div class="gauge-center"><span class="num">{{ card4.score }}</span></div>
            </div>
            <div class="card-title">
              <span class="card-zh">韧性投资 · 预算效率</span>
              <span class="card-en">CAPITAL ALLOCATION</span>
            </div>
            <span class="badge" :style="{ background: BADGE[card4.grade.type].bg, color: BADGE[card4.grade.type].color }">
              {{ card4.grade.label }}<span class="badge-en">/ 高性价比</span>
            </span>
          </div>
          <div class="metric-list">
            <div v-for="b in card4.bars" :key="b.label" class="metric-row">
              <div class="metric-label"><span>{{ b.label }}</span><span class="num">{{ b.value }}</span></div>
              <div class="progress-track"><div class="progress-fill success" :style="{ width: b.pct + '%' }"></div></div>
            </div>
          </div>
          <div class="card-summary">预算梯度优化：资金优先投向路网韧性而非增设医疗点</div>
          <div class="card-reco">加固关键路段的边际收益约为医疗点的 10 倍——医疗崩溃的根源在交通</div>
        </div>
      </section>

      <!-- ===== 综合评分总览 ===== -->
      <section class="summary-section">
        <div class="section-header">
          <span class="zh">综合压测评分</span>
          <span class="en">/ OVERALL STRESS SUMMARY</span>
        </div>
        <div class="summary-grid">
          <div class="summary-score">
            <div class="gauge-large">
              <svg viewBox="0 0 120 120" class="gauge-ring">
                <circle cx="60" cy="60" r="54" fill="none" stroke="var(--av-border)" stroke-width="8" />
                <circle cx="60" cy="60" r="54" fill="none" :stroke="GAUGE_COLOR[overall.grade.type]" stroke-width="8" stroke-linecap="round"
                        stroke-dasharray="339.3" :stroke-dashoffset="339.3 * (1 - overall.avg / 100)" />
              </svg>
              <div class="gauge-large-center"><span class="num">{{ overall.avg }}</span></div>
            </div>
            <div class="overall-label">
              <span class="overall-grade" :style="{ color: GAUGE_COLOR[overall.grade.type] }">{{ overall.grade.label }}</span>
              <span class="overall-cn">综合压测评分</span>
            </div>
          </div>
          <div>
            <table class="score-table">
              <thead>
                <tr><th>维度 / Dimension</th><th>得分 / Score</th><th>等级 / Grade</th></tr>
              </thead>
              <tbody>
                <tr v-for="r in overall.rows" :key="r.name">
                  <td>{{ r.name }}</td>
                  <td class="num">{{ r.score }}</td>
                  <td><span class="badge" :style="{ background: BADGE[r.grade.type].bg, color: BADGE[r.grade.type].color }">{{ r.grade.label }}</span></td>
                </tr>
              </tbody>
            </table>
          </div>
          <div>
            <div class="rec-title">总体建议 / RECOMMENDATIONS</div>
            <div v-for="(r, i) in recs" :key="i" class="rec-item">
              <div class="rec-icon" :style="{ color: r.color }"><component :is="r.icon" :size="16" /></div>
              <div class="rec-text">{{ r.text }}</div>
            </div>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.export-bar { display: flex; align-items: center; gap: 8px; margin: 0 0 10px; }
.export-btn { display: inline-flex; align-items: center; gap: 4px; padding: 3px 10px; font-size: 10px; font-weight: 600; color: var(--av-primary); background: var(--primary-dim); border: 1px solid var(--primary-border); border-radius: 3px; cursor: pointer; }
.export-hint { font-size: 9px; color: var(--av-muted-foreground); }

/* ===== 2x2 卡片网格（参考"分项综合分析"结构） ===== */
.analysis-cards {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}
.analysis-card {
  background: var(--av-card, #0B1018);
  border: 1px solid var(--av-border);
  border-radius: 12px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.card-head { display: flex; align-items: center; gap: 10px; }
.gauge-wrap { position: relative; width: 46px; height: 46px; flex-shrink: 0; }
.gauge-ring { transform: rotate(-90deg); width: 100%; height: 100%; }
.gauge-center { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; }
.gauge-center .num { font-size: 13px; font-weight: 700; color: var(--av-foreground); font-family: var(--av-font-mono); }
.card-title { display: flex; flex-direction: column; flex: 1; min-width: 0; }
.card-zh { font-size: 13px; font-weight: 600; color: var(--av-foreground); }
.card-en { font-size: 9px; letter-spacing: 0.06em; color: var(--av-muted-foreground); }
.badge { display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px; border-radius: 999px; font-size: 10px; font-weight: 600; white-space: nowrap; }
.badge-en { opacity: 0.7; font-size: 8.5px; letter-spacing: 0.05em; }
.metric-list { display: flex; flex-direction: column; gap: 6px; }
.metric-row { display: flex; flex-direction: column; gap: 2px; }
.metric-label { display: flex; justify-content: space-between; font-size: 10px; color: var(--av-muted-foreground); }
.metric-label .num { color: var(--av-foreground); font-family: var(--av-font-mono); }
.progress-track { height: 4px; background: var(--av-muted); border-radius: 999px; overflow: hidden; }
.progress-fill { height: 100%; border-radius: 999px; background: var(--av-primary); }
.progress-fill.success { background: var(--state-success); }
.progress-fill.info { background: var(--state-info); }
.progress-fill.danger { background: var(--state-error); }
.card-summary { font-size: 10px; color: var(--av-muted-foreground); line-height: 1.5; }
.card-reco { font-size: 10px; color: var(--av-primary); line-height: 1.5; }
.danger-text { color: var(--state-error); }

/* ===== 综合评分总览 ===== */
.summary-section {
  background: var(--av-card, #0B1018);
  border: 1px solid var(--av-border);
  border-radius: 12px;
  padding: 16px 20px;
  margin-top: 14px;
}
.section-header { display: flex; align-items: baseline; gap: 8px; margin-bottom: 14px; }
.section-header .zh { font-size: 14px; font-weight: 600; color: var(--av-foreground); }
.section-header .en { font-size: 10px; color: var(--av-muted-foreground); letter-spacing: 0.08em; text-transform: uppercase; }
.summary-grid { display: grid; grid-template-columns: minmax(0, 0.7fr) minmax(0, 1.15fr) minmax(0, 1.4fr); gap: 24px; align-items: start; }
.summary-score { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 6px 0; }
.gauge-large { position: relative; width: 110px; height: 110px; }
.gauge-large-center { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; }
.gauge-large-center .num { font-size: 32px; font-weight: 700; color: var(--av-foreground); font-family: var(--av-font-mono); }
.overall-label { display: flex; flex-direction: column; align-items: center; gap: 2px; }
.overall-grade { font-size: 14px; font-weight: 700; }
.overall-cn { font-size: 10px; color: var(--av-muted-foreground); }
.score-table { width: 100%; border-collapse: collapse; }
.score-table th, .score-table td { padding: 8px 10px; text-align: left; border-bottom: 1px solid var(--av-border); font-size: 12px; }
.score-table th { color: var(--av-muted-foreground); font-weight: 500; font-size: 10px; letter-spacing: 0.05em; }
.score-table td { color: var(--av-foreground); }
.score-table td.num { font-family: var(--av-font-mono); }
.score-table tbody tr:last-child td { border-bottom: none; }
.rec-title { font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--av-muted-foreground); margin-bottom: 6px; }
.rec-item { display: flex; gap: 10px; padding: 7px 0; border-bottom: 1px solid var(--av-border); }
.rec-item:last-child { border-bottom: none; }
.rec-icon { flex-shrink: 0; width: 26px; height: 26px; border-radius: 6px; display: flex; align-items: center; justify-content: center; background: var(--av-muted); }
.rec-text { font-size: 11px; color: var(--av-foreground); line-height: 1.5; }
</style>
