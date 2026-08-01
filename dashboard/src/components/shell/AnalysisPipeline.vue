<script setup>
import { ArrowRight } from 'lucide-vue-next'

defineProps({
  modes: { type: Array, required: true },
  currentMode: { type: Number, required: true },
})

const emit = defineEmits(['switch'])
</script>

<template>
  <div class="pipeline">
    <div class="pipeline-label">分析流水线</div>
    <div class="pipeline-steps">
      <template v-for="(m, i) in modes" :key="m.id">
        <div
          class="pipeline-step"
          :class="{ active: currentMode === m.id }"
          @click="emit('switch', m.id)"
          :title="`${m.name} · ${m.sub}`"
        >
          <span class="pipeline-idx">{{ m.id }}</span>
          <span class="pipeline-name">{{ m.name }}</span>
        </div>
        <ArrowRight v-if="i < modes.length - 1" :size="10" class="pipeline-arrow" />
      </template>
    </div>
  </div>
</template>

<style scoped>
.pipeline {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 3px 16px;
  background: rgba(10, 19, 32, 0.6);
  border-bottom: 1px solid var(--av-border);
  overflow-x: auto;
  white-space: nowrap;
}
.pipeline-label {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.5px;
  color: var(--av-muted-foreground);
  flex-shrink: 0;
}
.pipeline-steps {
  display: flex;
  align-items: center;
  gap: 2px;
  flex: 1;
}
.pipeline-step {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 3px;
  cursor: pointer;
  border: 1px solid transparent;
  transition: all 0.15s;
}
.pipeline-step:hover { background: rgba(0, 212, 255, 0.08); }
.pipeline-step.active {
  background: var(--primary-dim);
  border-color: var(--primary-border);
}
.pipeline-idx {
  font-size: 8px;
  font-family: var(--av-font-mono);
  color: var(--av-muted-foreground);
}
.pipeline-step.active .pipeline-idx { color: var(--av-primary); }
.pipeline-name {
  font-size: 10px;
  font-weight: 600;
  color: var(--av-muted-foreground);
}
.pipeline-step.active .pipeline-name { color: var(--av-primary); }
.pipeline-arrow { color: var(--av-border); flex-shrink: 0; }
</style>
