<script setup>
import { Hexagon, Download, Bell, User } from 'lucide-vue-next'

const props = defineProps({
  modeName: { type: String, default: '格局' },
  modeEn: { type: String, default: 'PATTERN' },
  modeSub: { type: String, default: '网络拓扑' },
  statusTag: { type: String, default: '基线正常' },
  statusTagType: { type: String, default: 'green' },
  magTag: { type: String, default: '' }
})
</script>

<template>
  <header class="top-bar">
    <!-- 品牌 -->
    <div class="w-8 h-8 rounded-lg flex items-center justify-center" style="background-color:rgba(0,212,255,0.12);">
      <Hexagon :size="20" style="color:var(--av-primary);" />
    </div>
    <div class="flex flex-col leading-tight">
      <span class="text-sm font-bold">城域底线</span>
      <span class="text-[10px]" style="color:var(--av-muted-foreground);">Urban Lifeline Diagnosis</span>
    </div>
    <div class="h-6 w-px" style="background-color:var(--av-border);"></div>
    <!-- 当前模式 -->
    <div class="flex flex-col leading-tight">
      <span class="text-sm font-semibold">{{ modeName }} · {{ modeSub }}</span>
      <span class="text-[10px]" style="color:var(--av-muted-foreground);">{{ modeEn }}</span>
    </div>
    <!-- 右侧操作 -->
    <div class="ml-auto flex items-center gap-2">
      <span v-if="statusTag" class="tag" :class="`tag-${statusTagType}`">{{ statusTag }}</span>
      <span v-if="magTag" class="tag tag-accent">{{ magTag }}</span>
      <div class="h-6 w-px" style="background-color:var(--av-border);"></div>
      <button class="w-9 h-9 rounded-lg flex items-center justify-center transition-colors"
        style="border:1px solid var(--av-border); color:var(--av-muted-foreground);"
        onmouseover="this.style.color='var(--av-foreground)';this.style.backgroundColor='var(--av-card)'"
        onmouseout="this.style.color='var(--av-muted-foreground)';this.style.backgroundColor='transparent'">
        <Download :size="16" />
      </button>
      <button class="w-9 h-9 rounded-lg flex items-center justify-center transition-colors"
        style="border:1px solid var(--av-border); color:var(--av-muted-foreground);"
        onmouseover="this.style.color='var(--av-foreground)';this.style.backgroundColor='var(--av-card)'"
        onmouseout="this.style.color='var(--av-muted-foreground)';this.style.backgroundColor='transparent'">
        <Bell :size="16" />
      </button>
      <div class="w-9 h-9 rounded-full flex items-center justify-center"
        style="border:1px solid var(--av-border); background-color:var(--av-card); color:var(--av-muted-foreground);">
        <User :size="16" />
      </div>
    </div>
  </header>
</template>
