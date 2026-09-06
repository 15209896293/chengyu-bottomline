<script setup>
/**
 * MapContainer.vue — Leaflet 真实地图容器
 *
 * 功能：
 * - 高德瓦片底图 + CSS filter 深色化（契合 #060912 科技风）
 * - 真实 GeoJSON 图层：区县边界 / 路网 / 阻断路网 / 医院POI / 消防/避难/危险源 / 断裂带 / 烈度网格 / 震中
 * - 震级联动：切换震级自动更新阻断路网和烈度网格
 * - Canvas 渲染器：高效渲染 3000 条路段
 * - 图层可见性通过 props.layers 控制
 */
import { ref, onMounted, onUnmounted, watch } from 'vue'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

const props = defineProps({
  // 当前震级（影响阻断路网 + 烈度网格 + 震中）
  magnitude: { type: Number, default: 5.5 },
  // 图层可见性
  layers: {
    type: Object,
    default: () => ({
      districts: true,
      roads: true,
      blockedRoads: false,
      hospitals: true,
      rescue: false,
      shelters: false,
      hazards: false,
      fault: true,
      intensity: false,
      epicenter: false,
    }),
  },
  // 地图中心 [lat, lng]
  center: { type: Array, default: () => [31.8611, 117.2830] },
  // 缩放
  zoom: { type: Number, default: 10 },
})

const emit = defineEmits(['district-click', 'hospital-click', 'ready'])

const mapEl = ref(null)
let map = null
let baseLayer = null
const tileOffline = ref(false) // 底图瓦片不可用（离线演示）时提示
const layerRefs = {} // 各 Leaflet 图层引用
const layerData = {} // 各图层原始 GeoJSON 数据缓存
let loaded = false

// ==================== 颜色配置 ====================
const STYLE = {
  district: { color: '#1B2640', weight: 1, fillColor: '#0B1018', fillOpacity: 0.3 },
  districtHover: { color: '#00D9FF', weight: 1.5, fillColor: '#00D9FF', fillOpacity: 0.15 },
  road: { color: '#2A3F5F', weight: 0.8, opacity: 0.5 },
  block: {
    '正常':     { color: '#2A3F5F', weight: 0.8, opacity: 0.4 },
    '轻度损伤': { color: '#FFB800', weight: 1.5, opacity: 0.7 },
    '严重损伤': { color: '#FF3366', weight: 2, opacity: 0.8 },
    '完全阻断': { color: '#FF4444', weight: 2.5, opacity: 0.9 },
  },
  hospital: { color: '#00D9FF', radius: 3, fillOpacity: 0.8, weight: 0.5 },
  hospitalLost: { color: '#FF4444', radius: 3, fillOpacity: 0.8, weight: 0.5 },
  // 医院可达性着色（与 dashboard JSON map_layers.hospitals 的 accessibility 字段对应）
  hospitalReach: {
    '可达但受限': { color: '#FFB800', radius: 3, fillOpacity: 0.8, weight: 0.5 },
    '不可达':     { color: '#FF4444', radius: 3, fillOpacity: 0.8, weight: 0.5 },
    '正常可达':   { color: '#00FF94', radius: 3, fillOpacity: 0.8, weight: 0.5 },
    // 无该字段时的兜底色（青色）
    _default:     { color: '#00D9FF', radius: 3, fillOpacity: 0.8, weight: 0.5 },
  },
  rescue: { color: '#00FF94', radius: 3, fillOpacity: 0.8, weight: 0.5 },
  shelter: { color: '#5A6B82', radius: 3, fillOpacity: 0.8, weight: 0.5 },
  hazard: { color: '#FF4444', radius: 3, fillOpacity: 0.6, weight: 0.5 },
  fault: { color: '#FF4444', weight: 1.5, opacity: 0.8, dashArray: '6,4' },
  epicenter: { color: '#FF4444', radius: 8, fillOpacity: 0.4, weight: 2 },
}

// 烈度→颜色映射
function intensityColor(i) {
  if (i >= 8) return '#FF4444'
  if (i >= 7) return '#FF3366'
  if (i >= 6) return '#FFB800'
  if (i >= 5) return '#00FF94'
  if (i >= 4) return '#00FF94'
  return '#5A6B82'
}

// ==================== 地图初始化 ====================
onMounted(() => {
  map = L.map(mapEl.value, {
    center: props.center,
    zoom: props.zoom,
    zoomControl: false,
    attributionControl: false,
    preferCanvas: true, // Canvas 渲染器，高效渲染大量矢量要素
    minZoom: 8,
    maxZoom: 16,
  })

  // 高德瓦片底图 + 深色 filter
  baseLayer = L.tileLayer(
    'https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}',
    { subdomains: '1234', maxZoom: 18, className: 'amap-dark-tiles' }
  )
  baseLayer.addTo(map)

  // 瓦片加载失败 fallback：隐藏底图，保留深色背景，并提示离线模式
  baseLayer.on('tileerror', () => {
    if (baseLayer._errorCount === undefined) baseLayer._errorCount = 0
    baseLayer._errorCount++
    if (baseLayer._errorCount > 5) {
      map.removeLayer(baseLayer)
      baseLayer = null
      tileOffline.value = true
    }
  })
  // 瓦片恢复可用时清除离线提示
  baseLayer.on('tileload', () => {
    if (tileOffline.value) tileOffline.value = false
  })

  L.control.zoom({ position: 'bottomright' }).addTo(map)

  loadAllLayers()
})

onUnmounted(() => {
  if (map) { map.remove(); map = null }
})

// ==================== 图层加载 ====================
async function loadAllLayers() {
  const geoBase = import.meta.env.BASE_URL + 'data/geo'
  // 分批加载，避免浏览器并发连接限制（HTTP/1.1 同域最多6个并发）
  const batch1 = [
    ['districts', 'hefei_districts_4490.geojson', createDistricts],
    ['hospitals', 'hefei_hospital.geojson', createHospitals],
    ['fault', 'tanlu_fault_hefei_4490.geojson', createFault],
  ]
  const batch2 = [
    ['roads', 'hefei_roads_lite.geojson', createRoads],
    ['rescue', 'facilities_rescue_real.geojson', createRescue],
    ['shelters', 'facilities_shelters_real.geojson', createShelters],
    ['hazards', 'facilities_hazards_real.geojson', createHazards],
  ]

  for (const batch of [batch1, batch2]) {
    await Promise.allSettled(
      batch.map(([key, fn_name, creator]) =>
        fetchGeo(`${geoBase}/${fn_name}`)
          .then(d => { layerData[key] = d; creator() })
          .catch(e => console.error(`图层 ${key} 加载失败:`, e))
      )
    )
  }

  // 阻断路网 + 烈度 + 震中 依赖震级
  await loadMagnitudeLayers()

  loaded = true
  updateVisibility()
  emit('ready', map)
}

async function fetchGeo(url, retries = 3) {
  for (let i = 0; i <= retries; i++) {
    try {
      const r = await fetch(url)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      return await r.json()
    } catch (e) {
      if (i === retries) throw e
      await new Promise(r => setTimeout(r, 300 * (i + 1)))
    }
  }
}

// --- 区县边界 ---
function createDistricts() {
  if (!layerData.districts) return
  layerRefs.districts = L.geoJSON(layerData.districts, {
    style: () => ({ ...STYLE.district }),
    onEachFeature: (feat, lyr) => {
      const name = feat.properties.name || ''
      lyr.bindTooltip(name, { permanent: false, direction: 'center', className: 'map-district-label' })
      lyr.on('mouseover', e => e.target.setStyle(STYLE.districtHover))
      lyr.on('mouseout', e => e.target.setStyle(STYLE.district))
      lyr.on('click', () => emit('district-click', feat.properties))
    },
  })
}

// --- 路网底图 ---
function createRoads() {
  if (!layerData.roads) return
  layerRefs.roads = L.geoJSON(layerData.roads, {
    style: () => ({ ...STYLE.road }),
    renderer: L.canvas(),
    interactive: false,
  })
}

// --- 阻断路网（按震级） ---
async function loadBlockedRoads(reqId) {
  const mag = props.magnitude.toFixed(1)
  const url = `${import.meta.env.BASE_URL}data/geo/road_blocked_M${mag}_lite.geojson`
  try {
    const data = await fetchGeo(url)
    if (reqId != null && reqId !== magnitudeReqId) return // 过期请求丢弃
    layerData.blockedRoads = data
    if (layerRefs.blockedRoads) { map.removeLayer(layerRefs.blockedRoads); layerRefs.blockedRoads = null }
    layerRefs.blockedRoads = L.geoJSON(data, {
      style: feat => {
        const lvl = feat.properties.block_level || '正常'
        return { ...(STYLE.block[lvl] || STYLE.block['正常']) }
      },
      renderer: L.canvas(),
      onEachFeature: (feat, lyr) => {
        lyr.bindTooltip(`${feat.properties.block_level || ''}`, { sticky: true })
      },
    })
    if (props.layers.blockedRoads && loaded) layerRefs.blockedRoads.addTo(map)
  } catch (e) { console.error('阻断路网加载失败:', e) }
}

// --- 医院POI ---
function createHospitals() {
  if (!layerData.hospitals) return
  layerRefs.hospitals = L.geoJSON(layerData.hospitals, {
    pointToLayer: (feat, latlng) => L.circleMarker(latlng, { ...STYLE.hospital }),
    onEachFeature: (feat, lyr) => {
      lyr.bindTooltip(`<b>${feat.properties.name}</b><br/>${feat.properties.type || ''}`, { sticky: true })
      lyr.on('click', () => emit('hospital-click', feat.properties))
    },
  })
}

// 按当前震级对医院可达性着色：医院数据源在 dashboard JSON 的 map_layers.hospitals（含 accessibility 字段）
// 替代静态 hefei_hospital.geojson（无可达性信息），使地图医院颜色与图例（不可达红/部分可达黄/可达绿）一致
async function loadHospitalsAccessibility(reqId) {
  const mag = props.magnitude.toFixed(1)
  try {
    const r = await fetch(`${import.meta.env.BASE_URL}data/dashboard_M${mag}.json`)
    const json = await r.json()
    if (reqId != null && reqId !== magnitudeReqId) return // 过期请求丢弃
    const list = json.map_layers?.hospitals || []
    if (!list.length) return
    if (layerRefs.hospitals) { map.removeLayer(layerRefs.hospitals); layerRefs.hospitals = null }
    layerRefs.hospitals = L.layerGroup(
      list.map(h => {
        const acc = h.accessibility
        const style = (acc && STYLE.hospitalReach[acc]) ? STYLE.hospitalReach[acc] : STYLE.hospitalReach._default
        return L.circleMarker([h.lat, h.lng], { ...style })
          .bindTooltip(`<b>${h.name}</b><br/>${acc || ''}`, { sticky: true })
      })
    )
    if (props.layers.hospitals && loaded) layerRefs.hospitals.addTo(map)
  } catch (e) { console.error('医院可达性着色失败:', e) }
}

function createRescue() {
  if (!layerData.rescue) return
  layerRefs.rescue = L.geoJSON(layerData.rescue, {
    pointToLayer: (feat, latlng) => L.circleMarker(latlng, { ...STYLE.rescue }),
    onEachFeature: (feat, lyr) => lyr.bindTooltip(`<b>${feat.properties.name}</b>`, { sticky: true }),
  })
}

function createShelters() {
  if (!layerData.shelters) return
  layerRefs.shelters = L.geoJSON(layerData.shelters, {
    pointToLayer: (feat, latlng) => L.circleMarker(latlng, { ...STYLE.shelter }),
    onEachFeature: (feat, lyr) => lyr.bindTooltip(`<b>${feat.properties.name}</b><br/>容量: ${feat.properties.capacity || '?'}`, { sticky: true }),
  })
}

function createHazards() {
  if (!layerData.hazards) return
  layerRefs.hazards = L.geoJSON(layerData.hazards, {
    pointToLayer: (feat, latlng) => L.circleMarker(latlng, { ...STYLE.hazard }),
    onEachFeature: (feat, lyr) => lyr.bindTooltip(`<b>${feat.properties.name}</b><br/>${feat.properties.subtype || ''}`, { sticky: true }),
  })
}

function createFault() {
  if (!layerData.fault) return
  layerRefs.fault = L.geoJSON(layerData.fault, {
    style: () => ({ ...STYLE.fault }),
    interactive: false,
  })
}

// --- 烈度网格（从 dashboard JSON 加载） ---
async function loadIntensity(reqId) {
  const mag = props.magnitude.toFixed(1)
  try {
    const r = await fetch(`${import.meta.env.BASE_URL}data/dashboard_M${mag}.json`)
    const json = await r.json()
    if (reqId != null && reqId !== magnitudeReqId) return // 过期请求丢弃
    const grid = json.map_layers?.intensity_grid || []
    // 采样：只显示烈度 >= 5 的点，最多 2000 个
    const filtered = grid.filter(p => p.intensity >= 5.0)
    const sampled = filtered.length > 2000
      ? filtered.filter((_, i) => i % Math.ceil(filtered.length / 2000) === 0)
      : filtered
    if (layerRefs.intensity) { map.removeLayer(layerRefs.intensity); layerRefs.intensity = null }
    layerRefs.intensity = L.layerGroup(
      sampled.map(p => L.circleMarker([p.lat, p.lng], {
        radius: 3,
        color: intensityColor(p.intensity),
        fillOpacity: 0.5,
        weight: 0,
      }))
    )
    if (props.layers.intensity && loaded) layerRefs.intensity.addTo(map)
  } catch (e) { console.error('烈度网格加载失败:', e) }
}

// --- 震中 ---
function loadEpicenter(reqId) {
  const mag = props.magnitude.toFixed(1)
  fetch(`${import.meta.env.BASE_URL}data/dashboard_M${mag}.json`)
    .then(r => r.json())
    .then(json => {
      if (reqId != null && reqId !== magnitudeReqId) return // 过期请求丢弃
      const epi = json.meta?.epicenter
      if (!epi) return
      if (layerRefs.epicenter) { map.removeLayer(layerRefs.epicenter); layerRefs.epicenter = null }
      const latlng = [epi.lat, epi.lng]
      layerRefs.epicenter = L.layerGroup([
        L.circleMarker(latlng, { ...STYLE.epicenter, radius: 10, fillOpacity: 0.2 }),
        L.circleMarker(latlng, { ...STYLE.epicenter, radius: 5, fillOpacity: 0.6 }),
        L.circleMarker(latlng, { radius: 2, color: '#FF4444', fillColor: '#FF4444', fillOpacity: 1, weight: 0 }),
      ])
      if (props.layers.epicenter && loaded) layerRefs.epicenter.addTo(map)
    })
    .catch(e => console.error('震中加载失败:', e))
}

// --- 震级相关图层统一加载 ---
// 防竞态：快速连续切换震级时，只应用最新一次请求的结果，避免旧请求晚返回覆盖新图层
let magnitudeReqId = 0
async function loadMagnitudeLayers() {
  const reqId = ++magnitudeReqId
  await Promise.all([
    loadBlockedRoads(reqId),
    loadIntensity(reqId),
    loadEpicenter(reqId),
    loadHospitalsAccessibility(reqId),
  ])
}

// ==================== 图层可见性控制 ====================
function updateVisibility() {
  if (!loaded || !map) return
  for (const [key, ref] of Object.entries(layerRefs)) {
    if (!ref) continue
    const visible = props.layers[key]
    if (visible && !map.hasLayer(ref)) ref.addTo(map)
    else if (!visible && map.hasLayer(ref)) map.removeLayer(ref)
  }
}

// ==================== Watchers ====================
// 震级变化 → 重新加载震级相关图层
watch(() => props.magnitude, () => {
  if (loaded) loadMagnitudeLayers()
})

// 图层可见性变化 → 更新显示
watch(() => props.layers, () => {
  if (loaded) updateVisibility()
}, { deep: true })

// ==================== expose ====================
defineExpose({
  getMap: () => map,
  flyTo: (latlng, zoom) => map?.flyTo(latlng, zoom || map.getZoom()),
  fitBounds: (bounds) => map?.fitBounds(bounds),
  invalidate: () => map?.invalidateSize(),
})
</script>

<template>
  <div class="map-container">
    <div ref="mapEl" class="leaflet-map" />
    <div v-if="tileOffline" class="tile-offline-tip">
      <span class="tile-offline-dot" /> 离线模式 · 底图不可用，数据图层正常显示
    </div>
  </div>
</template>

<style scoped>
.map-container {
  width: 100%;
  height: 100%;
  position: relative;
  background: #060912;
  border-radius: 6px;
  overflow: hidden;
}
.leaflet-map {
  width: 100%;
  height: 100%;
  background: #060912;
}
/* 离线底图提示条 */
.tile-offline-tip {
  position: absolute;
  top: 8px;
  left: 8px;
  z-index: 500;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  font-size: 10px;
  color: var(--muted, #5A6B82);
  background: rgba(17, 26, 42, 0.85);
  border: 1px solid var(--border, #1B2640);
  border-radius: 4px;
  backdrop-filter: blur(4px);
  pointer-events: none;
}
.tile-offline-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--warning, #FFB800);
}
</style>

<style>
/* 高德瓦片深色化 filter */
.amap-dark-tiles .leaflet-tile {
  filter: invert(1) hue-rotate(180deg) brightness(0.85) contrast(1.15) saturate(0.7);
}

/* Leaflet 控件深色化 */
.leaflet-control-zoom a {
  background: rgba(17, 26, 42, 0.9) !important;
  color: #00D9FF !important;
  border-color: #1B2640 !important;
}
.leaflet-control-zoom a:hover {
  background: rgba(0, 217, 255, 0.15) !important;
}

/* tooltip 深色化 */
.leaflet-tooltip {
  background: rgba(17, 26, 42, 0.95) !important;
  color: #E2E8F0 !important;
  border: 1px solid #1B2640 !important;
  border-radius: 4px !important;
  font-size: 11px !important;
  font-family: var(--font-sans, sans-serif) !important;
  padding: 4px 8px !important;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.4) !important;
}
.leaflet-tooltip-top:before,
.leaflet-tooltip-bottom:before,
.leaflet-tooltip-left:before,
.leaflet-tooltip-right:before {
  border-top-color: #1B2640 !important;
  border-bottom-color: #1B2640 !important;
  border-left-color: #1B2640 !important;
  border-right-color: #1B2640 !important;
}

/* 区县标签 */
.map-district-label {
  background: transparent !important;
  border: none !important;
  color: #5A6B82 !important;
  font-size: 10px !important;
  font-weight: 500 !important;
  text-shadow: 0 0 4px rgba(10, 19, 32, 0.8) !important;
}

/* Leaflet 容器背景 */
.leaflet-container {
  background: #060912 !important;
  font-family: var(--font-sans, sans-serif) !important;
}
.leaflet-tile-pane {
  z-index: 0;
}
</style>
