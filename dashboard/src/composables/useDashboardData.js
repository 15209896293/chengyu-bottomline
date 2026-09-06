import { ref, reactive, watch } from 'vue'
import { useMagnitude } from './useMagnitude'

/**
 * Dashboard 数据加载 composable
 *
 * 根据当前震级自动加载对应的 dashboard_M{X}.json
 * 提供 kpi / map_layers / charts / prevention / cascade 各数据段
 */

const { currentMag } = useMagnitude()

// 缓存已加载的数据
const cache = new Map()

// 响应式状态
const loading = ref(false)
const loadingProgress = ref(0) // 加载进度 0-100%
const error = ref(null)
const data = reactive({
  meta: null,
  kpi: null,
  map_layers: null,
  charts: null,
  prevention: null,
  cascade: null,
  sensitivity: null,
  time_evolution: null,
})

// 全震级 cascade 摘要（用于跨震级对比）
const allCascade = ref([])

/**
 * 加载指定震级的 dashboard JSON
 */
async function loadDashboard(mag) {
  const key = `M${mag.toFixed(1)}`
  if (cache.has(key)) {
    return cache.get(key)
  }
  const resp = await fetch(`${import.meta.env.BASE_URL}data/dashboard_${key}.json`)
  if (!resp.ok) {
    throw new Error(`加载 ${key} 数据失败: ${resp.status}`)
  }
  const json = await resp.json()
  cache.set(key, json)
  return json
}

/**
 * 更新响应式数据
 */
function updateData(json) {
  data.meta = json.meta
  data.kpi = json.kpi
  data.map_layers = json.map_layers
  data.charts = json.charts
  data.prevention = json.prevention
  data.cascade = json.cascade
  data.sensitivity = json.sensitivity
  data.time_evolution = json.time_evolution
}

/**
 * 加载所有震级的 cascade 摘要（用于跨震级图表）
 */
async function loadAllCascadeSummary() {
  if (allCascade.value.length > 0) return
  const { magnitudes } = useMagnitude()
  const summary = []
  for (const mag of magnitudes) {
    try {
      const json = await loadDashboard(mag)
      if (json.cascade) {
        summary.push({
          mag,
          medical: json.cascade.systems?.medical?.cascade_ratio ?? 0,
          rescue: json.cascade.systems?.rescue?.cascade_ratio ?? 0,
          transport: json.cascade.systems?.transport?.cascade_ratio ?? 0,
          shelter: json.cascade.systems?.shelter?.cascade_ratio ?? 0,
          city_collapse: json.cascade.city_cascade_collapse ?? false,
          cascade_depth: json.cascade.cascade_depth ?? 0,
        })
      }
    } catch (e) {
      console.error(`加载 M${mag} cascade 摘要失败:`, e)
    }
  }
  allCascade.value = summary
}

// 请求ID — 防止快速切换震级时竞态条件（仅最新请求的结果会被应用）
let lastRequestId = 0
// 进度模拟计时器
let progressTimer = null

/**
 * 启动加载进度模拟（0→90 平滑递增，真实加载完成后再跳到 100）
 */
function startProgress() {
  clearInterval(progressTimer)
  loadingProgress.value = 0
  progressTimer = setInterval(() => {
    if (loadingProgress.value < 90) {
      // 越接近 90 增长越慢，营造真实加载感
      const remain = 90 - loadingProgress.value
      loadingProgress.value = Math.min(90, loadingProgress.value + remain * 0.12 + 1)
    }
  }, 120)
}

/**
 * 完成加载进度（置 100）
 */
function finishProgress() {
  clearInterval(progressTimer)
  progressTimer = null
  loadingProgress.value = 100
}

// 监听震级变化，自动加载数据
watch(currentMag, async (mag) => {
  const reqId = ++lastRequestId
  loading.value = true
  error.value = null
  startProgress()
  try {
    const json = await loadDashboard(mag)
    // 过期请求丢弃，避免竞态覆盖最新数据
    if (reqId !== lastRequestId) return
    updateData(json)
  } catch (e) {
    if (reqId !== lastRequestId) return
    error.value = e.message
    console.error(e)
  } finally {
    if (reqId === lastRequestId) {
      finishProgress()
      loading.value = false
    }
  }
}, { immediate: true })

export function useDashboardData() {
  return {
    data,
    loading,
    loadingProgress,
    error,
    allCascade,
    loadAllCascadeSummary,
    reload: async () => {
      cache.clear()
      const reqId = ++lastRequestId
      loading.value = true
      error.value = null
      startProgress()
      try {
        const json = await loadDashboard(currentMag.value)
        if (reqId !== lastRequestId) return
        updateData(json)
      } catch (e) {
        if (reqId !== lastRequestId) return
        error.value = e.message
      } finally {
        if (reqId === lastRequestId) {
          finishProgress()
          loading.value = false
        }
      }
    },
  }
}
