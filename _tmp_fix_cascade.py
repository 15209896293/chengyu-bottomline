# 给 CascadeMode 追加缺失的局部样式（node-detail 浮层 + evo-guide 引导）
p = 'dashboard/src/components/modes/CascadeMode.vue'
c = open(p, encoding='utf-8').read()

if '</style>' in c:
    print('[SKIP] CascadeMode 已有 style 块')
else:
    style = '''
<style scoped>
/* 节点依赖详情浮层（此前 Replace('</style>') 静默失败导致缺失） */
.node-detail {
  position: absolute;
  top: 40px; left: 10px; z-index: 20;
  min-width: 155px;
  background: rgba(15, 26, 43, 0.96);
  border: 1px solid var(--av-border);
  border-radius: 6px;
  padding: 7px 9px;
  font-size: 9.5px;
  backdrop-filter: blur(4px);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.35);
}
.node-detail-head {
  display: flex; align-items: center; gap: 6px;
  font-weight: 700; font-size: 11px;
  margin-bottom: 4px;
}
.node-detail-status {
  font-size: 8px; color: var(--av-muted-foreground);
  background: rgba(126, 145, 172, 0.15);
  padding: 0 4px; border-radius: 2px;
}
.node-detail-close {
  margin-left: auto; cursor: pointer;
  color: var(--av-muted-foreground);
  font-size: 10px;
}
.node-detail-close:hover { color: var(--av-foreground); }
.node-detail-row {
  display: flex; justify-content: space-between; gap: 10px;
  padding: 1.5px 0; color: var(--av-muted-foreground);
}
.node-detail-row b {
  color: var(--av-foreground);
  font-family: var(--av-font-mono);
  font-size: 9.5px;
}
.node-detail-sec {
  font-size: 8px; color: var(--av-primary);
  margin-top: 4px; letter-spacing: 0.03em;
}

/* 时间步进播放引导（呼吸动画） */
.evo-guide {
  font-size: 8.5px; color: var(--state-warning);
  font-weight: 600; margin-left: 8px;
  padding: 1px 7px;
  border: 1px solid var(--state-warning);
  border-radius: 3px;
  animation: evo-pulse 1.6s ease-in-out infinite;
}
@keyframes evo-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
</style>
'''
    open(p, 'w', encoding='utf-8').write(c.rstrip() + '\n' + style)
    print('[OK] CascadeMode scoped style 已追加')
