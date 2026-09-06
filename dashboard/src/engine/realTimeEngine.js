/**
 * realTimeEngine.js — 前端实时推演引擎
 *
 * 与 Python 算法管线逐公式对齐（step20_reverse_stress / cascade_model）：
 *   - 俞言祥2013 烈度衰减（intensity_model._yu2013）
 *   - 基础功能率 6 档插值/外推（step20.interpolate_base_rates）
 *   - 迭代级联传播（cascade_model._iterate_to_convergence）
 *   - 崩溃判定（cascade_model.judge_collapse / system_status / city_collapsed）
 *
 * 用途：拖拽震级/参数 → 浏览器内实时重算，替代"切震级→加载 1.6MB JSON"。
 * 自检：selfTest() 与内嵌 Python 参考值对比（误差 < 0.001 视为一致）。
 */

// ═══════════════ 模型常量（与 config.yaml / collapse_threshold.csv 一致） ═══════════════
const BASE_RATES_6 = [
  { mag: 5.0, medical: 0.5423, rescue: 0.4156, transport: 0.6122, shelter: Math.min(11.5968, 1) },
  { mag: 5.5, medical: 0.2676, rescue: 0.4156, transport: 0.6006, shelter: Math.min(3.4294, 1) },
  { mag: 6.0, medical: 0.2617, rescue: 0.3766, transport: 0.5927, shelter: Math.min(1.9136, 1) },
  { mag: 6.5, medical: 0.2617, rescue: 0.3636, transport: 0.5825, shelter: Math.min(1.0105, 1) },
  { mag: 7.0, medical: 0.2441, rescue: 0.3333, transport: 0.5713, shelter: 0.4379 },
  { mag: 7.5, medical: 0.2347, rescue: 0.3030, transport: 0.5566, shelter: 0.2454 },
]

const DEPENDENCY_MATRIX = {
  medical: { transport: 0.45, rescue: 0.15 },
  rescue: { transport: 0.55, medical: 0.20 },
  shelter: { medical: 0.38, rescue: 0.52, transport: 0.20 },
  transport: {},
}

const THRESHOLDS = { medical: 0.30, rescue: 0.40, transport: 0.50, shelter: 0.30 }

const SYSTEM_KEYS = ['medical', 'transport', 'rescue', 'shelter']
const SYSTEM_NAMES = { medical: '医疗', transport: '交通', rescue: '救援', shelter: '避难' }
const SYSTEM_COLORS = { medical: '#FF4444', transport: '#FFB800', rescue: '#FF3366', shelter: '#00FF94' }

// 俞言祥2013 系数（config.yaml intensity.yu2013）
const YU2013_PARAMS = { c1: 1.785, c2: 1.352, c3: 1.038, c4: 0.017, c5: 0.494 }

const MIN_MAG = 5.0
const MAX_MAG = 7.5

// ═══════════════ 烈度衰减 ═══════════════
export function calcIntensity(mag, distKm, params = YU2013_PARAMS) {
  const R = Math.max(Number(distKm) || 0, 0.1)
  return params.c1 + params.c2 * mag - params.c3 * Math.log(R + params.c4 * Math.exp(params.c5 * mag))
}

// ═══════════════ 基础功能率插值/外推（与 step20 一致） ═══════════════
export function interpolateBaseRates(mag, base = BASE_RATES_6) {
  const mags = base.map(r => r.mag)
  const out = {}
  for (const key of ['medical', 'rescue', 'transport', 'shelter']) {
    const vals = base.map(r => r[key])
    let v
    if (mag < mags[0]) {
      const slope = (vals[1] - vals[0]) / (mags[1] - mags[0])
      v = vals[0] + slope * (mag - mags[0])
    } else if (mag > mags[mags.length - 1]) {
      const slope = (vals[mags.length - 1] - vals[mags.length - 2]) / (mags[mags.length - 1] - mags[mags.length - 2])
      v = vals[mags.length - 1] + slope * (mag - mags[mags.length - 1])
    } else {
      // 线性插值
      let i = 0
      while (i < mags.length - 1 && mag > mags[i + 1]) i++
      const t = (mag - mags[i]) / (mags[i + 1] - mags[i])
      v = vals[i] + (vals[i + 1] - vals[i]) * t
    }
    out[key] = Math.min(Math.max(v, 0.05), 1.0)
  }
  return out
}

// ═══════════════ 级联迭代（与 cascade_model 逐行一致） ═══════════════
export function cascadeIterate(baseRates, dep = DEPENDENCY_MATRIX, opts = {}) {
  const maxIter = opts.maxIterations || 100
  const tol = opts.tolerance || 0.0001
  const c = { ...baseRates }
  for (let it = 0; it < maxIter; it++) {
    const prev = { ...c }
    c.transport = baseRates.transport
    const tLoss = 1 - c.transport
    const mLoss = 1 - c.medical
    const rLoss = 1 - c.rescue
    c.medical = Math.max(0, baseRates.medical
      * (1 - dep.medical.transport * tLoss)
      * (1 - dep.medical.rescue * rLoss))
    c.rescue = Math.max(0, baseRates.rescue
      * (1 - dep.rescue.transport * tLoss)
      * (1 - dep.rescue.medical * mLoss))
    c.shelter = Math.max(0, baseRates.shelter
      * (1 - dep.shelter.medical * mLoss)
      * (1 - dep.shelter.rescue * rLoss)
      * (1 - dep.shelter.transport * tLoss))
    let maxChange = 0
    for (const k of SYSTEM_KEYS) maxChange = Math.max(maxChange, Math.abs(c[k] - prev[k]))
    if (maxChange < tol) break
  }
  // 与 Python round(x, 4) 对齐
  const r4 = v => Math.round(v * 10000) / 10000
  return { medical: r4(c.medical), transport: r4(c.transport), rescue: r4(c.rescue), shelter: r4(c.shelter) }
}

export function computeCascade(baseRates, propagationFactor = 1.0, dep = DEPENDENCY_MATRIX) {
  const full = cascadeIterate(baseRates, dep)
  if (propagationFactor >= 1.0) return full
  if (propagationFactor <= 0.0) {
    const r4 = v => Math.round(v * 10000) / 10000
    return { medical: r4(baseRates.medical), transport: r4(baseRates.transport), rescue: r4(baseRates.rescue), shelter: r4(baseRates.shelter) }
  }
  const r4 = v => Math.round(v * 10000) / 10000
  return {
    medical: r4(baseRates.medical + (full.medical - baseRates.medical) * propagationFactor),
    transport: r4(baseRates.transport + (full.transport - baseRates.transport) * propagationFactor),
    rescue: r4(baseRates.rescue + (full.rescue - baseRates.rescue) * propagationFactor),
    shelter: r4(baseRates.shelter + (full.shelter - baseRates.shelter) * propagationFactor),
  }
}

// ═══════════════ 崩溃判定 ═══════════════
export function judgeCollapse(ratio, systemKey, thresholds = THRESHOLDS) {
  return ratio < (thresholds[systemKey] ?? 0.3)
}

export function systemStatus(ratio, systemKey, thresholds = THRESHOLDS) {
  const thr = thresholds[systemKey] ?? 0.3
  if (ratio < thr) return '已崩溃'
  if (ratio < thr * 1.2) return '级联风险'
  if (ratio < thr * 1.5) return '承压'
  return '正常'
}

export function cityCollapsed(cascade, thresholds = THRESHOLDS) {
  return SYSTEM_KEYS.some(k => judgeCollapse(cascade[k], k, thresholds))
}

// ═══════════════ 综合推演：震级 → 完整状态 ═══════════════
export function calcCityState(mag, opts = {}) {
  const dep = opts.dependencyMatrix || DEPENDENCY_MATRIX
  const thresholds = opts.thresholds || THRESHOLDS
  const base = interpolateBaseRates(mag)
  const cascade = cascadeIterate(base, dep, opts)
  const systems = {}
  for (const k of SYSTEM_KEYS) {
    systems[k] = {
      name: SYSTEM_NAMES[k],
      color: SYSTEM_COLORS[k],
      baseRatio: base[k],
      cascadeRatio: cascade[k],
      drop: Math.round((base[k] - cascade[k]) * 10000) / 10000,
      collapsed: judgeCollapse(cascade[k], k, thresholds),
      status: systemStatus(cascade[k], k, thresholds),
    }
  }
  return {
    magnitude: Math.round(mag * 100) / 100,
    base,
    cascade,
    systems,
    cityCollapsed: cityCollapsed(cascade, thresholds),
    collapsedCount: SYSTEM_KEYS.filter(k => systems[k].collapsed).length,
  }
}

// ═══════════════ 自定义震中推演（一阶近似） ═══════════════
// 思路与 step20 震中扫描一致：人口加权平均烈度差 dI_bar →
// 功能率线性偏移 Δrate = -coef × dI_bar × (1 - rate)。
// 距离档案：人口按距断裂带质心距离分桶（grid_distance_profile.json），
// 偏移近似 d_new = sqrt(d0² + offset²)（沿断裂带走向破裂，城区在两侧）。
const DEFAULT_PROFILE = {
  repDistKm: [3.5, 8.0, 12.5, 17.5, 22.5, 27.5, 35, 45, 55, 70, 92],
  weight: [0.02, 0.08, 0.15, 0.18, 0.14, 0.12, 0.10, 0.08, 0.06, 0.04, 0.03],
  epicenter: [117.28, 31.82],
}

const INTENSITY_SENSITIVITY = { transport: 0.15, medical: 0.10, rescue: 0.10, shelter: 0.08 }

export function calcCityStateAtOffset(mag, offsetKm, opts = {}) {
  const profile = opts.distanceProfile || DEFAULT_PROFILE
  const dep = opts.dependencyMatrix || DEPENDENCY_MATRIX
  const thresholds = opts.thresholds || THRESHOLDS
  const base = interpolateBaseRates(mag)

  // 人口加权平均烈度（质心 vs 偏移后）
  const d0 = profile.repDistKm
  const dNew = d0.map(d => Math.sqrt(d * d + offsetKm * offsetKm))
  const w = profile.weight
  const I0 = d0.reduce((s, d, i) => s + w[i] * calcIntensity(mag, d), 0)
  const I1 = dNew.reduce((s, d, i) => s + w[i] * calcIntensity(mag, d), 0)
  const dI = I1 - I0  // 偏移后烈度变化（通常为负）

  // 功能率调整（一阶代理，同 step20）
  const adj = {}
  for (const k of SYSTEM_KEYS) {
    const raw = base[k] - INTENSITY_SENSITIVITY[k] * dI * (1 - base[k])
    adj[k] = Math.min(Math.max(raw, 0.05), 1.0)
  }
  const cascade = cascadeIterate(adj, dep, opts)

  const systems = {}
  for (const k of SYSTEM_KEYS) {
    systems[k] = {
      name: SYSTEM_NAMES[k],
      color: SYSTEM_COLORS[k],
      baseRatio: adj[k],
      cascadeRatio: cascade[k],
      drop: Math.round((adj[k] - cascade[k]) * 10000) / 10000,
      collapsed: judgeCollapse(cascade[k], k, thresholds),
      status: systemStatus(cascade[k], k, thresholds),
    }
  }
  return {
    magnitude: Math.round(mag * 100) / 100,
    offsetKm,
    dI,
    base: adj,
    cascade,
    systems,
    cityCollapsed: cityCollapsed(cascade, thresholds),
    collapsedCount: SYSTEM_KEYS.filter(k => systems[k].collapsed).length,
  }
}

// ═══════════════ 自检（Node 环境用） ═══════════════
export function selfTest() {
  // Python cascade_model.compute_all_magnitudes 参考值（compute_cascade, propagation=1.0）
  const pyRef = {
    5.0: { medical: 0.3998, transport: 0.6122, rescue: 0.2877, shelter: 0.4483 },
    5.5: { medical: 0.1955, transport: 0.6006, rescue: 0.2721, shelter: 0.397 },
    6.0: { medical: 0.1895, transport: 0.5927, rescue: 0.2449, shelter: 0.386 },
    6.5: { medical: 0.1881, transport: 0.5825, rescue: 0.2346, shelter: 0.3815 },
    7.0: { medical: 0.1737, transport: 0.5713, rescue: 0.2126, shelter: 0.1622 },
    7.5: { medical: 0.1651, transport: 0.5566, rescue: 0.1908, shelter: 0.0884 },
  }
  const failures = []
  for (const [mStr, ref] of Object.entries(pyRef)) {
    const mag = Number(mStr)
    const state = calcCityState(mag)
    for (const k of SYSTEM_KEYS) {
      const err = Math.abs(state.cascade[k] - ref[k])
      if (err > 0.001) failures.push(`M${mag} ${k}: JS=${state.cascade[k]} Python=${ref[k]} err=${err}`)
    }
  }
  return failures
}

export { BASE_RATES_6, DEPENDENCY_MATRIX, THRESHOLDS, SYSTEM_KEYS, SYSTEM_NAMES, SYSTEM_COLORS, MIN_MAG, MAX_MAG }
