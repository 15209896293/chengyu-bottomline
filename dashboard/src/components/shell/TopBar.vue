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
    <div class="w-8 h-8 flex items-center justify-center" style="background-color:rgba(0,217,255,0.12);clip-path:var(--clip-btn);border:1px solid var(--primary-border);">
      <Hexagon :size="20" style="color:var(--av-primary);filter:drop-shadow(0 0 4px var(--primary-glow));" />
    </div>
    <div class="flex flex-col leading-tight">
      <span class="text-sm font-bold">城域底线</span>
      <span class="text-[10px]" style="color:var(--av-muted-foreground);font-family:var(--av-font-mono);letter-spacing:0.1em;">URBAN LIFELINE</span>
    </div>
    <div class="h-6 w-px" style="background-color:var(--av-border);"></div>
    <!-- 当前模式 -->
    <div class="flex flex-col leading-tight">
      <span class="text-sm font-semibold">{{ modeName }} · {{ modeSub }}</span>
      <span class="text-[10px]" style="color:var(--av-muted-foreground);font-family:var(--av-font-mono);letter-spacing:0.1em;">{{ modeEn }}</span>
    </div>
    <!-- 右侧操作 -->
    <div class="ml-auto flex items-center gap-2">
      <span v-if="statusTag" class="tag" :class="`tag-${statusTagType}`">{{ statusTag }}</span>
      <span v-if="magTag" class="tag tag-accent">{{ magTag }}</span>
      <div class="h-6 w-px" style="background-color:var(--av-border);"></div>
      <button class="w-9 h-9 flex items-center justify-center transition-all"
        style="clip-path:var(--clip-btn);border:1px solid var(--av-border); color:var(--av-muted-foreground);background:transparent;"
        onmouseover="this.style.color='var(--av-primary)';this.style.backgroundColor='rgba(0,217,255,0.08)';this.style.borderColor='var(--primary-border)'"
        onmouseout="this.style.color='var(--av-muted-foreground)';this.style.backgroundColor='transparent';this.style.borderColor='var(--av-border)'">
        <Download :size="16" />
      </button>
      <button class="w-9 h-9 flex items-center justify-center transition-all"
        style="clip-path:var(--clip-btn);border:1px solid var(--av-border); color:var(--av-muted-foreground);background:transparent;"
        onmouseover="this.style.color='var(--av-primary)';this.style.backgroundColor='rgba(0,217,255,0.08)';this.style.borderColor='var(--primary-border)'"
        onmouseout="this.style.color='var(--av-muted-foreground)';this.style.backgroundColor='transparent';this.style.borderColor='var(--av-border)'">
        <Bell :size="16" />
      </button>
      <div class="w-9 h-9 flex items-center justify-center"
        style="clip-path:var(--clip-btn);border:1px solid var(--av-border); background-color:var(--av-card); color:var(--av-muted-foreground);">
        <User :size="16" />
      </div>
    </div>
  </header>
</template>
