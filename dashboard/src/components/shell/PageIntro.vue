<script setup>
import { HelpCircle } from 'lucide-vue-next'

defineProps({
  // 本页回答的核心问题（一句话）
  question: { type: String, required: true },
  // 可选：本页的 2-3 个看点（数组）
  points: { type: Array, default: () => [] },
  // 可选：强调色（默认主色）
  color: { type: String, default: 'var(--av-primary)' },
})
</script>

<template>
  <div class="page-intro">
    <div class="page-intro-bar" :style="{ background: color }"></div>
    <div class="page-intro-body">
      <div class="page-intro-tag">
        <HelpCircle :size="11" style="vertical-align:-1px;" />
        <span>本页回答</span>
      </div>
      <div class="page-intro-question">{{ question }}</div>
      <div v-if="points && points.length" class="page-intro-points">
        <span v-for="(p, i) in points" :key="i" class="page-intro-point">{{ p }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-intro {
  display: flex;
  align-items: stretch;
  gap: 0;
  background: rgba(17, 26, 42, 0.5);
  border: 1px solid var(--av-border);
  border-radius: 4px;
  overflow: hidden;
  margin: 2px 0 8px;
}
.page-intro-bar { width: 3px; flex-shrink: 0; }
.page-intro-body { flex: 1; padding: 6px 10px; }
.page-intro-tag {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.5px;
  color: var(--av-primary);
  margin-bottom: 2px;
}
.page-intro-question {
  font-size: 12px;
  font-weight: 600;
  color: var(--av-foreground);
  line-height: 1.4;
}
.page-intro-points {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 4px;
}
.page-intro-point {
  font-size: 9.5px;
  color: var(--av-muted-foreground);
  background: rgba(90, 107, 130, 0.1);
  border: 1px solid rgba(90, 107, 130, 0.2);
  border-radius: 2px;
  padding: 1px 6px;
}
</style>
