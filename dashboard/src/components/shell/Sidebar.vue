<script setup>
import { Hexagon, LayoutGrid, Activity, GitBranch, ShieldCheck, FlaskConical, CheckCircle2, Gauge } from 'lucide-vue-next'

const props = defineProps({
  modes: { type: Array, required: true },
  currentMode: { type: Number, required: true }
})

const emit = defineEmits(['switch'])

const iconMap = {
  'layout-grid': LayoutGrid,
  'activity': Activity,
  'git-branch': GitBranch,
  'shield-check': ShieldCheck,
  'flask-conical': FlaskConical,
  'check-circle': CheckCircle2,
  'gauge': Gauge
}
</script>

<template>
  <aside class="sidebar">
    <div class="sidebar-brand">
      <Hexagon :size="20" style="color:var(--av-primary);" />
    </div>
    <template v-for="g in ['核心', '高级']" :key="g">
      <div v-if="g === '高级'" class="nav-divider">{{ g }}</div>
      <div
        v-for="mode in modes.filter(m => m.group === g)"
        :key="mode.id"
        class="nav-item"
        :class="{ active: currentMode === mode.id }"
        @click="emit('switch', mode.id)"
      >
        <component :is="iconMap[mode.icon]" :size="20" class="nav-icon" />
        <div class="nav-tooltip">
          <div class="nav-tooltip-title">0{{ mode.id }} {{ mode.name }}</div>
          <div class="nav-tooltip-sub">{{ mode.sub }}</div>
        </div>
      </div>
    </template>
  </aside>
</template>

<style scoped>
.nav-divider {
  font-size: 8px;
  letter-spacing: 0.5px;
  color: var(--av-muted-foreground);
  text-align: center;
  padding: 6px 0 2px;
  border-top: 1px solid var(--av-border);
  margin: 2px 8px 0;
}
</style>
