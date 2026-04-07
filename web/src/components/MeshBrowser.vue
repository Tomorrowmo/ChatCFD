<script setup>
import { ref, watch, computed, onMounted } from 'vue'
import VtkViewer from './VtkViewer.vue'
import { useChatStore } from '../stores/chat.js'

const props = defineProps({
  data: Object, // loadFile summary (initial data, refreshed from API)
})

const { activeConversation } = useChatStore()
const sessionId = computed(() => activeConversation.value?.id || 'default')
const selectedZone = ref('')
const selectedScalar = ref('')
const liveZones = ref([])
const loading = ref(false)

// Use live data if available, fall back to artifact snapshot
const zones = computed(() => liveZones.value.length ? liveZones.value : (props.data?.zones || []))
const currentZoneScalars = computed(() => {
  const z = zones.value.find((x) => x.name === selectedZone.value)
  return z?.scalars || []
})

// Fetch latest zone/scalar info from backend (picks up post-calculation changes)
async function refreshZones() {
  try {
    loading.value = true
    const resp = await fetch(`http://localhost:8000/api/zones/${sessionId.value}`)
    if (resp.ok) {
      const data = await resp.json()
      if (data.zones) {
        liveZones.value = data.zones
      }
    }
  } catch (e) {
    console.warn('[MeshBrowser] Failed to refresh zones:', e.message)
  } finally {
    loading.value = false
  }
}

function autoSelect() {
  const z = zones.value
  if (z.length && (!selectedZone.value || !z.find(x => x.name === selectedZone.value))) {
    selectedZone.value = z[0].name
    const firstScalar = z[0].scalars?.[0]
    selectedScalar.value = firstScalar?.raw_name || ''
  }
}

watch(() => props.data, () => { autoSelect() }, { immediate: true })
watch(liveZones, () => { autoSelect() })

watch(selectedZone, () => {
  const scalars = currentZoneScalars.value
  if (scalars.length && !scalars.find((s) => s.raw_name === selectedScalar.value)) {
    selectedScalar.value = scalars[0].raw_name
  }
})

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
      <button class="refresh-btn" @click="refreshZones" :disabled="loading" title="刷新标量列表">
        {{ loading ? '...' : '↻' }}
      </button>
    </div>
    <VtkViewer
      :key="`${sessionId}-${selectedZone}-${selectedScalar}`"
      :sessionId="sessionId"
      :zone="selectedZone"
      :scalarName="selectedScalar"
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
</style>
