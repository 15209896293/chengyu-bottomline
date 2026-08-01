<script setup>
import { computed } from 'vue'
import { useMode } from './composables/useMode'
import { useMagnitude } from './composables/useMagnitude'
import AppShell from './components/shell/AppShell.vue'
import PatternMode from './components/modes/PatternMode.vue'
import ThresholdMode from './components/modes/ThresholdMode.vue'
import CascadeMode from './components/modes/CascadeMode.vue'
import ResilienceMode from './components/modes/ResilienceMode.vue'
import SandboxMode from './components/modes/SandboxMode.vue'
import ValidationMode from './components/modes/ValidationMode.vue'
import StressMode from './components/modes/StressMode.vue'

const { modes, currentMode, mode, switchMode } = useMode()
const { currentMag } = useMagnitude()

const modeEn = computed(() => mode.value?.en || '')
const modeSub = computed(() => mode.value?.sub || '')

// 各模式的顶栏状态标签（Mode 02 动态响应震级）
const statusTag = computed(() => {
  switch (currentMode.value) {
    case 1: return '基线正常'
    case 2: return currentMag.value < 5.5 ? '全系统正常' : '城市已崩溃'
    case 3: return currentMag.value >= 5.5 ? '级联传播中' : '系统承压'
    case 4: return '策略C最优'
    case 5: return '500次蒙特卡洛'
    case 6: return '2震例+4震源'
    case 7: return '逆压测+VaR95'
    default: return ''
  }
})

const statusTagType = computed(() => {
  switch (currentMode.value) {
    case 1: return 'green'
    case 2: return currentMag.value < 5.5 ? 'green' : 'red'
    case 3: return 'yellow'
    case 4: return 'green'
    case 5: return 'purple'
    case 6: return 'green'
    case 7: return 'accent'
    default: return 'green'
  }
})

const magTag = computed(() => {
  switch (currentMode.value) {
    case 1: return '基线'
    case 2: return 'M' + currentMag.value.toFixed(1)
    case 3: return 'M' + currentMag.value.toFixed(1)
    case 4: return 'M' + currentMag.value.toFixed(1)
    case 5: return 'M' + currentMag.value.toFixed(1)
    case 6: return 'yu2013'
    case 7: return 'M6.0'
    default: return ''
  }
})

const currentComponent = computed(() => {
  switch (currentMode.value) {
    case 1: return PatternMode
    case 2: return ThresholdMode
    case 3: return CascadeMode
    case 4: return ResilienceMode
    case 5: return SandboxMode
    case 6: return ValidationMode
    case 7: return StressMode
    default: return PatternMode
  }
})
</script>

<template>
  <AppShell
    :mode-name="mode.name"
    :mode-en="modeEn"
    :mode-sub="modeSub"
    :modes="modes"
    :current-mode="currentMode"
    :status-tag="statusTag"
    :status-tag-type="statusTagType"
    :mag-tag="magTag"
    @switch-mode="switchMode"
  >
    <Transition name="fade-mode" mode="out-in" :duration="300">
      <component :is="currentComponent" :key="currentMode" />
    </Transition>
  </AppShell>
</template>
