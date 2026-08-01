import { ref, computed } from 'vue'

/**
 * 模式状态管理 — 6个模式切换
 * 1=格局  2=临界  3=级联  4=韧性  5=沙盘  6=验证
 */

const MODES = [
  { id: 1, key: 'pattern',    name: '格局', sub: '网络拓扑',   en: 'PATTERN',            icon: 'layout-grid' },
  { id: 2, key: 'threshold', name: '临界', sub: '崩溃阈值',   en: 'COLLAPSE THRESHOLD', icon: 'activity' },
  { id: 3, key: 'cascade',    name: '级联', sub: '传播路径',   en: 'CASCADE ANALYSIS',   icon: 'git-branch' },
  { id: 4, key: 'resilience', name: '韧性', sub: '策略优化',   en: 'RESILIENCE',         icon: 'shield-check' },
  { id: 5, key: 'sandbox',    name: '沙盘', sub: '参数敏感性', en: 'SENSITIVITY SANDBOX', icon: 'flask-conical' },
  { id: 6, key: 'validation', name: '验证', sub: '模型验证',   en: 'VALIDATION',         icon: 'check-circle' }
]

const currentMode = ref(1) // 默认从格局模式开始

export function useMode() {
  const mode = computed(() => MODES.find(m => m.id === currentMode.value))

  function switchMode(id) {
    currentMode.value = id
  }

  return { modes: MODES, currentMode, mode, switchMode }
}
