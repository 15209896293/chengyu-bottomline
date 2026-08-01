import { ref, computed } from 'vue'

/**
 * 模式状态管理 — 6个模式切换
 * 1=格局  2=临界  3=级联  4=韧性  5=沙盘  6=验证
 */

const MODES = [
  { id: 1, key: 'pattern',    name: '格局', sub: '网络拓扑',   en: 'PATTERN',            icon: 'layout-grid',   group: '核心' },
  { id: 2, key: 'threshold', name: '临界', sub: '崩溃阈值',   en: 'COLLAPSE THRESHOLD', icon: 'activity',      group: '核心' },
  { id: 3, key: 'cascade',    name: '级联', sub: '传播路径',   en: 'CASCADE ANALYSIS',   icon: 'git-branch',   group: '核心' },
  { id: 4, key: 'resilience', name: '决策', sub: '底线推移·预算', en: 'DECISION COCKPIT', icon: 'gauge',        group: '核心' },
  { id: 5, key: 'sandbox',    name: '沙盘', sub: '参数敏感性', en: 'SENSITIVITY SANDBOX', icon: 'flask-conical', group: '高级' },
  { id: 6, key: 'validation', name: '验证', sub: '模型验证',   en: 'VALIDATION',         icon: 'check-circle', group: '高级' },
  { id: 7, key: 'stress',     name: '压测', sub: '逆压测·VaR', en: 'REVERSE STRESS',     icon: 'gauge',        group: '高级' }
]

const currentMode = ref(1) // 默认从格局模式开始

export function useMode() {
  const mode = computed(() => MODES.find(m => m.id === currentMode.value))

  function switchMode(id) {
    currentMode.value = id
  }

  return { modes: MODES, currentMode, mode, switchMode }
}
