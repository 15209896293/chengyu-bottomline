import { ref, computed } from 'vue'

/**
 * 震级状态管理 — 6档离散滑块
 * M5.0 / M5.5 / M6.0 / M6.5 / M7.0 / M7.5
 */

const MAGNITUDES = [5.0, 5.5, 6.0, 6.5, 7.0, 7.5]

const currentMag = ref(5.5) // 默认M5.5（崩溃临界点）

export function useMagnitude() {
  const magIndex = computed(() => {
    const idx = MAGNITUDES.indexOf(currentMag.value)
    return idx >= 0 ? idx : 1
  })

  function setMagnitude(value) {
    const idx = MAGNITUDES.indexOf(value)
    if (idx >= 0) currentMag.value = value
  }

  function setMagIndex(idx) {
    if (idx >= 0 && idx < MAGNITUDES.length) {
      currentMag.value = MAGNITUDES[idx]
    }
  }

  return { magnitudes: MAGNITUDES, currentMag, magIndex, setMagnitude, setMagIndex }
}
