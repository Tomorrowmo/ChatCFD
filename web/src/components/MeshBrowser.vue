<script setup>
import { ref, watch, computed, onMounted } from 'vue'
import VtkViewer from './VtkViewer.vue'
import TimeControls from './TimeControls.vue'
import { useChatStore } from '../stores/chat.js'

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
const liveZones = ref([])
const loading = ref(false)
const currentFrame = ref(0)
const timeControlsRef = ref(null)
const liveFrameCount = ref(0)
const liveTimeLabels = ref([])
const maxCache = ref(50)
const scalarRanges = ref({})  // {zone: {scalar: [min, max]}} — global across all frames
const frameCount = computed(() => liveFrameCount.value || props.data?.frame_count || 1)
const timeLabels = computed(() => liveTimeLabels.value.length ? liveTimeLabels.value : (props.data?.time_labels || []))

// Global scalar range for the current zone+scalar selection (multi-frame consistency)
const currentScalarRange = computed(() => {
  const zoneRanges = scalarRanges.value[selectedZone.value]
  if (!zoneRanges) return null
  const range = zoneRanges[selectedScalar.value]
  return range || null  // [min, max] or null
})

// Use live data if available, fall back to artifact snapshot
const zones = computed(() => liveZones.value.length ? liveZones.value : (props.data?.zones || []))
const currentZoneScalars = computed(() => {
  const z = zones.value.find((x) => x.name === selectedZone.value)
  const scalars = z?.scalars || []
  return [...scalars].sort((a, b) => (a.display_name || a.raw_name).localeCompare(b.display_name || b.raw_name))
})

const fileParam = computed(() => props.sourceFile ? `?file=${encodeURIComponent(props.sourceFile)}` : '')

// Fetch latest zone/scalar info from backend (picks up post-calculation changes)
async function refreshZones() {
  try {
    loading.value = true
    const resp = await fetch(`http://localhost:8000/api/zones/${sessionId.value}${fileParam.value}`)
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
  if (z.length && (forceReset || !selectedZone.value || !z.find(x => x.name === selectedZone.value))) {
    selectedZone.value = z[0].name
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
    await fetch(`http://localhost:8000/api/frame_cache/${sessionId.value}?${params}`, { method: 'PUT' })
  } catch (e) {
    console.warn('[MeshBrowser] Failed to set frame cache:', e.message)
  }
}

onMounted(() => { refreshZones() })
watch(sessionId, () => { refreshZones() })
</script>

<template>
  <div class="mesh-browser">
    <div class="controls">
      <label>
        Zone:
        <select v-model="selectedZone">
          <option v-for="z in zones" :key="z.name" :value="z.name">
            {{ z.name }} ({{ z.point_count || z.n_points || '?' }} pts)
          </option>
        </select>
      </label>
      <label>
        Scalar:
        <select v-model="selectedScalar">
          <option value="">None (geometry)</option>
          <option v-for="s in currentZoneScalars" :key="s.raw_name" :value="s.raw_name">
            {{ s.display_name || s.raw_name }}
          </option>
        </select>
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
    </div>
    <VtkViewer
      :key="`${sessionId}-${sourceFile}-${selectedZone}-${selectedScalar}-${displayMode}-${colorPreset}`"
      :sessionId="sessionId"
      :sourceFile="sourceFile"
      :zone="selectedZone"
      :scalarName="selectedScalar"
      :displayMode="displayMode"
      :opacity="opacity"
      :colorPreset="colorPreset"
      :frame="currentFrame"
      :scalarRange="currentScalarRange"
      @loaded="timeControlsRef?.frameReady()"
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
