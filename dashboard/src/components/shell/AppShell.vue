<script setup>
import TopBar from './TopBar.vue'
import Sidebar from './Sidebar.vue'
import AnalysisPipeline from './AnalysisPipeline.vue'

const props = defineProps({
  modeName: { type: String, default: '格局' },
  modeEn: { type: String, default: 'PATTERN' },
  modeSub: { type: String, default: '网络拓扑' },
  modes: { type: Array, required: true },
  currentMode: { type: Number, required: true },
  statusTag: { type: String, default: '' },
  statusTagType: { type: String, default: 'green' },
  magTag: { type: String, default: '' }
})

const emit = defineEmits(['switchMode'])
</script>

<template>
  <div class="app-shell">
    <TopBar
      :mode-name="modeName"
      :mode-en="modeEn"
      :mode-sub="modeSub"
      :status-tag="statusTag"
      :status-tag-type="statusTagType"
      :mag-tag="magTag"
    />
    <!-- 分析流水线：7 模式的因果链定位 -->
    <AnalysisPipeline
      :modes="modes"
      :current-mode="currentMode"
      @switch="emit('switchMode', $event)"
    />
    <div class="shell-body">
      <Sidebar
        :modes="modes"
        :current-mode="currentMode"
        @switch="emit('switchMode', $event)"
      />
      <main>
        <div class="main-content">
          <slot />
        </div>
      </main>
    </div>
  </div>
</template>
