<script setup>
import { ref, computed, watch } from 'vue'
import { Zap, SlidersHorizontal } from 'lucide-vue-next'
import { calcCityState, SYSTEM_KEYS, SYSTEM_NAMES, SYSTEM_COLORS } from '../../engine/realTimeEngine.js'

// ==================== 实时推演状态 ====================
const mag = ref(6.0)              // 连续震级 M5.0-7.5
const depTm = ref(0.45)           // 交通→医疗依赖（实时可调）

const state = computed(() => {
  const dep = {
    medical: { transport: depTm.value, rescue: 0.15 },
    rescue: { transport: 0.55, medical: 0.20 },
    shelter: { medical: 0.38, rescue: 0.52, transport: 0.20 },
    transport: {},
  }
  return calcCityState(mag.value, { dependencyMatrix: dep })
})

const bars = computed(() => SYSTEM_KEYS.map(k => ({
  key: k,
  name: SYSTEM_NAMES[k],
  color: SYSTEM_COLORS[k],
  ratio: state.value.cascade[k],
  status: state.value.systems[k].status,
  collapsed: state.value.systems[k].collapsed,
  drop: state.value.systems[k].drop,
})))

// 城市状态
const cityLabel = computed(() => {
  const s = state.value
  if (s.cityCollapsed) return { text: '城市已崩溃', color: 'var(--state-error)' }
  if (s.collapsedCount > 0) return { text: '部分系统承压', color: 'var(--state-warning)' }
  return { text: '全系统正常', color: 'var(--state-success)' }
})
</script>

<template>
  <div class="probe-panel">
    <div class="probe-header">
      <Zap :size="11" style="vertical-align:-1px;" color="var(--state-warning)" />
      <span>实时推演引擎 · 连续震级</span>
      <span class="probe-tag">REALTIME</span>
    </div>

    <!-- 连续震级滑块 -->
    <div class="probe-row">
      <div class="probe-label">震级 M<span class="probe-val">{{ mag.toFixed(1) }}</span></div>
      <input v-model.number="mag" type="range" min="5.0" max="7.5" step="0.1" class="probe-range" />
      <div class="probe-scale"><span>M5.0</span><span>M7.5</span></div>
    </div>

    <!-- 依赖权重微调 -->
    <div class="probe-row">
      <div class="probe-label">交通→医疗依赖 <span class="probe-val">{{ depTm.toFixed(2) }}</span></div>
      <input v-model.number="depTm" type="range" min="0.30" max="0.60" step="0.01" class="probe-range" />
      <div class="probe-scale"><span>0.30</span><span>0.60</span></div>
    </div>

    <!-- 系统功能率条 -->
    <div class="probe-bars">
      <div v-for="b in bars" :key="b.key" class="probe-bar-row">
        <div class="probe-bar-head">
          <span class="probe-bar-name" :style="{ color: b.color }">{{ b.name }}</span>
          <span class="probe-bar-meta">
            <span :style="{ color: b.collapsed ? 'var(--state-error)' : b.color }">
              {{ (b.ratio * 100).toFixed(1) }}%
            </span>
            <span v-if="b.drop > 0.005" class="probe-drop">▼{{ (b.drop * 100).toFixed(1) }}%</span>
            <span class="probe-status" :class="b.collapsed ? 'collapsed' : ''">{{ b.status }}</span>
          </span>
        </div>
        <div class="probe-track">
          <div class="probe-fill" :style="{ width: (b.ratio * 100) + '%', background: b.color }"></div>
        </div>
      </div>
    </div>

    <!-- 城市状态 -->
    <div class="probe-city" :style="{ color: cityLabel.color, borderColor: cityLabel.color + '44' }">
      {{ cityLabel.text }} · {{ state.collapsedCount }}/4 系统崩溃
    </div>
    <div class="probe-note">拖动实时计算（浏览器内引擎），中间震级如 M{{ mag.toFixed(1) }} 无需加载数据文件</div>
  </div>
</template>

<style scoped>
.probe-panel {
  background: rgba(15, 26, 43, 0.5);
  border: 1px solid var(--av-border);
  border-top: 2px solid var(--state-warning);
  border-radius: 4px;
  padding: 8px;
  margin-bottom: 8px;
}
.probe-header { display: flex; align-items: center; gap: 5px; font-size: 10.5px; font-weight: 700; color: var(--av-foreground); margin-bottom: 6px; }
.probe-tag { margin-left: auto; font-size: 8px; font-weight: 700; letter-spacing: 0.5px; color: var(--state-warning); border: 1px solid var(--state-warning); border-radius: 2px; padding: 0 3px; }
.probe-row { margin-bottom: 6px; }
.probe-label { font-size: 9.5px; color: var(--av-muted-foreground); margin-bottom: 2px; }
.probe-val { color: var(--av-primary); font-family: var(--av-font-mono); font-weight: 700; }
.probe-range { width: 100%; height: 4px; accent-color: var(--av-primary); cursor: pointer; }
.probe-scale { display: flex; justify-content: space-between; font-size: 8px; color: var(--av-muted-foreground); }
.probe-bars { display: flex; flex-direction: column; gap: 5px; margin: 8px 0; }
.probe-bar-row { display: flex; flex-direction: column; gap: 2px; }
.probe-bar-head { display: flex; justify-content: space-between; align-items: center; font-size: 9px; }
.probe-bar-name { font-weight: 700; }
.probe-bar-meta { display: flex; align-items: center; gap: 5px; font-family: var(--av-font-mono); }
.probe-drop { color: var(--state-error); font-size: 8px; }
.probe-status { font-size: 8px; color: var(--av-muted-foreground); font-family: var(--font-sans, sans-serif); padding: 0 3px; border-radius: 2px; background: rgba(126,145,172,0.15); }
.probe-status.collapsed { color: var(--state-error); background: rgba(248,113,113,0.15); }
.probe-track { height: 6px; background: rgba(15,26,43,0.8); border: 1px solid var(--av-border); border-radius: 2px; overflow: hidden; }
.probe-fill { height: 100%; border-radius: 1px; transition: width 0.08s linear; }
.probe-city { font-size: 10.5px; font-weight: 700; border: 1px dashed; border-radius: 3px; padding: 4px 6px; text-align: center; margin-top: 4px; }
.probe-note { font-size: 8.5px; color: var(--av-muted-foreground); margin-top: 5px; line-height: 1.4; }
</style>
