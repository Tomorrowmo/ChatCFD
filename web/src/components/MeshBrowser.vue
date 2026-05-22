<script setup>
import { ref, watch, computed, onMounted } from 'vue'
import { POST_SERVICE_URL } from '../config.js'
import VtkViewer from './VtkViewer.vue'
import TimeControls from './TimeControls.vue'
import { useChatStore } from '../stores/chat.js'
import { useFrameExport } from '../composables/useFrameExport.js'

const props = defineProps({
  data: Object, // loadFile summary (initial data, refreshed from API)
  sourceFile: { type: String, default: '' }, // source file path for multi-file sessions
})

const { activeConversation } = useChatStore()
const sessionId = computed(() => activeConversation.value?.id || 'default')
const selectedZone = ref('')
const selectedScalar = ref('')
const displayMode = ref('surface')  // 'surface' | 'surface+edges' | 'wireframe'
const opacity = ref(1.0)
const colorPreset = ref('jet')
const renderMode = ref('scalar')  // 'scalar' | 'vector'
const selectedVector = ref('')
const arrowScale = ref(1.0)
const availableVectors = ref([])  // populated by VtkViewer's arrays-detected event
const liveZones = ref([])
const loading = ref(false)
const currentFrame = ref(0)
const timeControlsRef = ref(null)
const viewerRef = ref(null)
const liveFrameCount = ref(0)
const liveTimeLabels = ref([])
const maxCache = ref(50)
const scalarRanges = ref({})  // {zone: {scalar: [min, max]}} — global across all frames
const frameCount = computed(() => liveFrameCount.value || props.data?.frame_count || 1)
const timeLabels = computed(() => liveTimeLabels.value.length ? liveTimeLabels.value : (props.data?.time_labels || []))

// Total point count across all zones (for the "All" option label)
const totalPoints = computed(() => zones.value.reduce((sum, z) => sum + (z.point_count || z.n_points || 0), 0))

// Global scalar range for the current zone+scalar selection (multi-frame consistency)
const currentScalarRange = computed(() => {
  const ranges = scalarRanges.value
  if (!Object.keys(ranges).length) return null
  const scalar = selectedScalar.value
  if (!scalar) return null

  if (selectedZone.value === '__all__') {
    // Merge range across all zones
    let lo = Infinity, hi = -Infinity
    for (const zr of Object.values(ranges)) {
      const r = zr[scalar]
      if (r) { lo = Math.min(lo, r[0]); hi = Math.max(hi, r[1]) }
    }
    return lo <= hi ? [lo, hi] : null
  }
  const zoneRanges = ranges[selectedZone.value]
  if (!zoneRanges) return null
  return zoneRanges[scalar] || null
})

// Use live data if available, fall back to artifact snapshot
const zones = computed(() => liveZones.value.length ? liveZones.value : (props.data?.zones || []))
// Dedup key: prefer display_name (so two raw names mapping to the same
// physical quantity collapse into one entry), fall back to standard_name,
// then raw_name. Same key is used for __all__ union and single-zone view.
function dedupKey(s) {
  return s.display_name || s.standard_name || s.raw_name
}

const currentZoneScalars = computed(() => {
  let source
  if (selectedZone.value === '__all__') {
    source = zones.value.flatMap((z) => z.scalars || [])
  } else {
    const z = zones.value.find((x) => x.name === selectedZone.value)
    source = z?.scalars || []
  }
  const seen = new Set()
  const scalars = []
  for (const s of source) {
    const key = dedupKey(s)
    if (!seen.has(key)) {
      seen.add(key)
      scalars.push(s)
    }
  }
  return scalars.sort((a, b) => dedupKey(a).localeCompare(dedupKey(b)))
})

const fileParam = computed(() => props.sourceFile ? `?file=${encodeURIComponent(props.sourceFile)}` : '')

// Fetch latest zone/scalar info from backend (picks up post-calculation changes)
async function refreshZones() {
  try {
    loading.value = true
    const resp = await fetch(`${POST_SERVICE_URL}/api/zones/${sessionId.value}${fileParam.value}`)
    if (resp.ok) {
      const data = await resp.json()
      if (data.zones) {
        liveZones.value = data.zones
        if (data.frame_count) liveFrameCount.value = data.frame_count
        if (data.time_labels) liveTimeLabels.value = data.time_labels
        if (data.max_cache) maxCache.value = data.max_cache
        if (data.scalar_ranges) {
          scalarRanges.value = data.scalar_ranges
        } else if (data.frame_count > 1 && !Object.keys(scalarRanges.value).length) {
          // Preload not ready yet — retry after a few seconds
          setTimeout(refreshZones, 3000)
        }
      }
    }
  } catch (e) {
    console.warn('[MeshBrowser] Failed to refresh zones:', e.message)
  } finally {
    loading.value = false
  }
}

function autoSelect(forceReset = false) {
  const z = zones.value
  if (z.length && (forceReset || !selectedZone.value || (selectedZone.value !== '__all__' && !z.find(x => x.name === selectedZone.value)))) {
    selectedZone.value = '__all__'
    const firstScalar = z[0].scalars?.[0]
    selectedScalar.value = firstScalar?.raw_name || ''
  }
}

watch(() => props.data, () => { autoSelect() }, { immediate: true })
watch(liveZones, () => { autoSelect() })

// When switching files, clear stale liveZones and re-fetch
watch(() => props.sourceFile, () => {
  liveZones.value = []
  autoSelect(true)
  refreshZones()
})

watch(selectedZone, () => {
  const scalars = currentZoneScalars.value
  if (scalars.length && !scalars.find((s) => s.raw_name === selectedScalar.value)) {
    selectedScalar.value = scalars[0].raw_name
  }
})

async function updateMaxCache(val) {
  maxCache.value = val
  const params = new URLSearchParams({ max_cache: String(val) })
  if (props.sourceFile) params.set('file', props.sourceFile)
  try {
    await fetch(`${POST_SERVICE_URL}/api/frame_cache/${sessionId.value}?${params}`, { method: 'PUT' })
  } catch (e) {
    console.warn('[MeshBrowser] Failed to set frame cache:', e.message)
  }
}

onMounted(() => { refreshZones() })
watch(sessionId, () => { refreshZones() })

// When the viewer reports the arrays present in the current frame, refresh
// our vector list and keep the user's pick if it still exists.
function onArraysDetected({ scalars, vectors }) {
  availableVectors.value = vectors || []
  if (selectedVector.value && !availableVectors.value.includes(selectedVector.value)) {
    selectedVector.value = availableVectors.value[0] || ''
  } else if (!selectedVector.value && availableVectors.value.length) {
    selectedVector.value = availableVectors.value[0]
  }
}

// Falling out of vector mode when no vectors are available
watch(availableVectors, (v) => {
  if (renderMode.value === 'vector' && !v.length) renderMode.value = 'scalar'
})

// Frame-sequence export (PNG zip / GIF)
const {
  exporting, progress: exportProgress, exportLabel,
  notifyLoaded, cancel: cancelExport, exportPNG, exportGIF, exportWEBM,
} = useFrameExport({ viewerRef, currentFrame, frameCount })

// VtkViewer 'loaded' drives both playback advance and export frame stepping
function onFrameLoaded() {
  timeControlsRef.value?.frameReady()
  notifyLoaded()
}
</script>

<template>
  <div class="mesh-browser">
    <div class="controls">
      <label>
        Zone:
        <select v-model="selectedZone">
          <option value="__all__">All Zones ({{ totalPoints }} pts)</option>
          <option v-for="z in zones" :key="z.name" :value="z.name">
            {{ z.name }} ({{ z.point_count || z.n_points || '?' }} pts)
          </option>
        </select>
      </label>
      <label class="mode-toggle">
        Mode:
        <span class="seg">
          <button :class="{ on: renderMode === 'scalar' }" @click="renderMode = 'scalar'">标量</button>
          <button :class="{ on: renderMode === 'vector' }" @click="renderMode = 'vector'" :disabled="!availableVectors.length" :title="availableVectors.length ? '' : '当前数据无向量字段'">向量</button>
        </span>
      </label>
      <label v-if="renderMode === 'scalar'">
        Scalar:
        <select v-model="selectedScalar">
          <option value="">None (geometry)</option>
          <option v-for="s in currentZoneScalars" :key="s.raw_name" :value="s.raw_name">
            {{ s.display_name || s.raw_name }}
          </option>
        </select>
      </label>
      <label v-else>
        Vector:
        <select v-model="selectedVector">
          <option v-for="v in availableVectors" :key="v" :value="v">{{ v }}</option>
        </select>
      </label>
      <label v-if="renderMode === 'vector'" class="opacity-label">
        Arrow:
        <input type="range" v-model.number="arrowScale" min="0.1" max="5" step="0.1" class="opacity-slider" />
        <span class="opacity-val">{{ arrowScale.toFixed(1) }}×</span>
      </label>
      <label>
        Display:
        <select v-model="displayMode">
          <option value="surface">Surface</option>
          <option value="surface+edges">Surface + Mesh</option>
          <option value="wireframe">Wireframe</option>
        </select>
      </label>
      <label>
        Color:
        <select v-model="colorPreset">
          <option value="jet">Jet</option>
          <option value="coolwarm">Cool-Warm</option>
          <option value="rainbow">Rainbow</option>
          <option value="viridis">Viridis</option>
          <option value="blueRed">Blue-Red</option>
          <option value="grayscale">Grayscale</option>
        </select>
      </label>
      <label class="opacity-label">
        Opacity:
        <input type="range" v-model.number="opacity" min="0" max="1" step="0.05" class="opacity-slider" />
        <span class="opacity-val">{{ Math.round(opacity * 100) }}%</span>
      </label>
      <button class="refresh-btn" @click="refreshZones" :disabled="loading" title="刷新标量列表">
        {{ loading ? '...' : '↻' }}
      </button>
    </div>
    <div class="time-row" v-if="frameCount > 1">
      <TimeControls
        ref="timeControlsRef"
        :frameCount="frameCount"
        :timeLabels="timeLabels"
        :bookmarkKey="`${sessionId}:${sourceFile}`"
        v-model="currentFrame"
      />
      <label class="cache-label">
        Cache:
        <select :value="maxCache" @change="updateMaxCache(Number($event.target.value))">
          <option :value="5">5</option>
          <option :value="10">10</option>
          <option :value="20">20</option>
          <option :value="50">50</option>
          <option :value="100">100</option>
          <option :value="200">200</option>
          <option :value="frameCount">All ({{ frameCount }})</option>
        </select>
      </label>
      <span class="export-group">
        <template v-if="!exporting">
          <button class="exp-btn" @click="exportPNG" title="导出每帧 PNG（打包为 ZIP）">导出 PNG</button>
          <button class="exp-btn" @click="exportGIF(5)" title="导出 GIF 动画">导出 GIF</button>
          <button class="exp-btn" @click="exportWEBM(10)" title="导出 WEBM 视频">导出 WEBM</button>
        </template>
        <template v-else>
          <span class="exp-progress">{{ exportLabel }} {{ Math.round(exportProgress * 100) }}%</span>
          <button class="exp-btn exp-cancel" @click="cancelExport">取消</button>
        </template>
      </span>
    </div>
    <VtkViewer
      ref="viewerRef"
      :key="`${sessionId}-${sourceFile}-${selectedZone}-${selectedScalar}-${displayMode}-${colorPreset}-${renderMode}-${selectedVector}`"
      :sessionId="sessionId"
      :sourceFile="sourceFile"
      :zone="selectedZone"
      :scalarName="selectedScalar"
      :displayMode="displayMode"
      :opacity="opacity"
      :colorPreset="colorPreset"
      :frame="currentFrame"
      :scalarRange="currentScalarRange"
      :renderMode="renderMode"
      :vectorName="selectedVector"
      :arrowScale="arrowScale"
      @loaded="onFrameLoaded"
      @arrays-detected="onArraysDetected"
    />
  </div>
</template>

<style scoped>
.mesh-browser {
  display: flex;
  flex-direction: column;
  height: 100%;
  gap: 8px;
  min-height: 0;
}

.controls {
  display: flex;
  gap: 12px;
  padding: 8px 12px;
  background: var(--bg-tertiary);
  border-radius: 6px;
  flex-shrink: 0;
  flex-wrap: wrap;
  align-items: center;
}

.controls label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-secondary);
}

.controls select {
  background: var(--bg-input, var(--bg-secondary));
  color: var(--text-primary);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 4px 8px;
  font-size: 12px;
  max-width: 260px;
}

.refresh-btn {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-secondary);
  border-radius: 4px;
  padding: 3px 8px;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.1s;
}
.refresh-btn:hover { background: var(--bg-tertiary); color: var(--text-primary); }
.refresh-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.opacity-label { white-space: nowrap; }
.opacity-slider { width: 70px; vertical-align: middle; accent-color: var(--accent); }
.opacity-val { display: inline-block; width: 32px; text-align: right; font-variant-numeric: tabular-nums; }

.mode-toggle .seg {
  display: inline-flex;
  border: 1px solid var(--border);
  border-radius: 4px;
  overflow: hidden;
}
.mode-toggle .seg button {
  background: transparent;
  color: var(--text-secondary);
  border: none;
  padding: 4px 10px;
  font-size: 12px;
  cursor: pointer;
}
.mode-toggle .seg button.on {
  background: var(--accent);
  color: #fff;
}
.mode-toggle .seg button:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
.mode-toggle .seg button + button { border-left: 1px solid var(--border); }

.export-group {
  display: flex;
  align-items: center;
  gap: 4px;
}
.exp-btn {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-secondary);
  border-radius: 4px;
  padding: 3px 8px;
  font-size: 11px;
  cursor: pointer;
  transition: background 0.1s, color 0.1s;
}
.exp-btn:hover { background: var(--bg-secondary); color: var(--text-primary); }
.exp-cancel { color: #d66; border-color: #d66; }
.exp-progress {
  font-size: 11px;
  color: var(--accent);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.time-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.cache-label {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
  flex-shrink: 0;
}
.cache-label select {
  background: var(--bg-input, var(--bg-secondary));
  color: var(--text-primary);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 2px 4px;
  font-size: 11px;
}
</style>
