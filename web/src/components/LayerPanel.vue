<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useChatStore } from '../stores/chat.js'

const props = defineProps({
  /** loadFile data with zones array, for "Add Zone" dropdown */
  meshData: { type: Object, default: null },
})

const {
  activeSceneLayers,
  activeConversation,
  addSceneLayer,
  removeSceneLayer,
  toggleLayerVisibility,
  clearSceneLayers,
} = useChatStore()

const sessionId = computed(() => activeConversation.value?.id || 'default')
const layers = computed(() => activeSceneLayers.value)

// "Add Zone" controls
const liveZones = ref([])
const newZone = ref('')
const newScalar = ref('')
const loadingZones = ref(false)
const showAddControls = ref(false)

const zones = computed(() =>
  liveZones.value.length ? liveZones.value : (props.meshData?.zones || [])
)

const currentZoneScalars = computed(() => {
  const z = zones.value.find(x => x.name === newZone.value)
  return z?.scalars || []
})

async function refreshZones() {
  try {
    loadingZones.value = true
    const resp = await fetch(`http://localhost:8000/api/zones/${sessionId.value}`)
    if (resp.ok) {
      const data = await resp.json()
      if (data.zones) liveZones.value = data.zones
    }
  } catch (e) {
    console.warn('[LayerPanel] Failed to refresh zones:', e.message)
  } finally {
    loadingZones.value = false
  }
}

// Auto-select first zone/scalar when zones change
watch(zones, (z) => {
  if (z.length && !newZone.value) {
    newZone.value = z[0].name
    const s = z[0].scalars?.[0]
    newScalar.value = s?.raw_name || ''
  }
})

watch(newZone, () => {
  const scalars = currentZoneScalars.value
  if (scalars.length) {
    newScalar.value = scalars[0].raw_name
  } else {
    newScalar.value = ''
  }
})

function addZoneLayer() {
  if (!newZone.value) return
  const scalarDisplay = newScalar.value || 'geometry'
  const name = `${newZone.value} (${scalarDisplay})`
  addSceneLayer({
    name,
    type: 'zone',
    source: {
      sessionId: sessionId.value,
      zone: newZone.value,
      scalarName: newScalar.value,
    },
  })
}

function toggleAdd() {
  showAddControls.value = !showAddControls.value
  if (showAddControls.value && zones.value.length === 0) {
    refreshZones()
  }
}

onMounted(() => {
  if (props.meshData?.zones?.length) {
    // Pre-populate from artifact data
    const z = props.meshData.zones
    if (z.length && !newZone.value) {
      newZone.value = z[0].name
      const s = z[0].scalars?.[0]
      newScalar.value = s?.raw_name || ''
    }
  }
})
</script>

<template>
  <div class="layer-panel">
    <div class="panel-header">
      <span class="panel-title">Layers</span>
      <span class="layer-count" v-if="layers.length">{{ layers.length }}</span>
      <button class="icon-btn" @click="clearSceneLayers" title="Clear all layers" v-if="layers.length">
        <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
    </div>

    <div class="layer-list" v-if="layers.length">
      <div
        v-for="layer in layers"
        :key="layer.id"
        class="layer-item"
        :class="{ hidden: !layer.visible }"
      >
        <button
          class="vis-btn"
          @click="toggleLayerVisibility(layer.id)"
          :title="layer.visible ? 'Hide' : 'Show'"
        >
          <svg v-if="layer.visible" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
            <circle cx="12" cy="12" r="3"/>
          </svg>
          <svg v-else viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/>
            <line x1="1" y1="1" x2="23" y2="23"/>
          </svg>
        </button>
        <span class="layer-name" :title="layer.name">{{ layer.name }}</span>
        <span class="layer-type-badge">{{ layer.type === 'zone' ? 'Z' : 'F' }}</span>
        <button class="remove-btn" @click="removeSceneLayer(layer.id)" title="Remove layer">&times;</button>
      </div>
    </div>
    <div v-else class="empty-hint">No layers. Add a zone or analysis result.</div>

    <div class="add-section">
      <button class="add-toggle-btn" @click="toggleAdd">
        {{ showAddControls ? '- Cancel' : '+ Add Zone' }}
      </button>
      <div v-if="showAddControls" class="add-controls">
        <select v-model="newZone" class="add-select">
          <option value="" disabled>Select zone...</option>
          <option v-for="z in zones" :key="z.name" :value="z.name">
            {{ z.name }}
          </option>
        </select>
        <select v-model="newScalar" class="add-select">
          <option value="">None (geometry)</option>
          <option v-for="s in currentZoneScalars" :key="s.raw_name" :value="s.raw_name">
            {{ s.display_name || s.raw_name }}
          </option>
        </select>
        <div class="add-actions">
          <button class="add-btn" @click="addZoneLayer" :disabled="!newZone">Add</button>
          <button class="refresh-btn" @click="refreshZones" :disabled="loadingZones" title="Refresh zones">
            {{ loadingZones ? '...' : '&#x21bb;' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.layer-panel {
  flex-shrink: 0;
  border-top: 1px solid var(--border);
  background: var(--bg-secondary);
  max-height: 260px;
  display: flex;
  flex-direction: column;
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.panel-title {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-secondary);
}

.layer-count {
  font-size: 10px;
  padding: 0 5px;
  border-radius: 8px;
  background: var(--accent);
  color: #fff;
  font-weight: 600;
  line-height: 16px;
}

.icon-btn {
  margin-left: auto;
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  padding: 2px;
  border-radius: 4px;
  display: flex;
  align-items: center;
}
.icon-btn:hover { color: var(--text-primary); background: var(--bg-tertiary); }

.layer-list {
  overflow-y: auto;
  flex: 1;
  min-height: 0;
}

.layer-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  font-size: 12px;
  transition: background 0.1s;
}
.layer-item:hover { background: var(--bg-hover, rgba(255,255,255,0.03)); }
.layer-item.hidden { opacity: 0.5; }

.vis-btn {
  background: none;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  padding: 2px;
  display: flex;
  align-items: center;
  flex-shrink: 0;
}
.vis-btn:hover { color: var(--text-primary); }

.layer-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-primary);
}

.layer-type-badge {
  font-size: 9px;
  font-weight: 700;
  padding: 1px 4px;
  border-radius: 3px;
  background: var(--bg-tertiary);
  color: var(--text-muted);
  flex-shrink: 0;
}

.remove-btn {
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 16px;
  line-height: 1;
  padding: 0 2px;
  flex-shrink: 0;
}
.remove-btn:hover { color: #e55; }

.empty-hint {
  padding: 10px 12px;
  font-size: 11px;
  color: var(--text-muted);
  text-align: center;
}

.add-section {
  border-top: 1px solid var(--border);
  padding: 6px 12px;
  flex-shrink: 0;
}

.add-toggle-btn {
  width: 100%;
  padding: 4px 8px;
  font-size: 11px;
  font-weight: 600;
  background: transparent;
  border: 1px dashed var(--border);
  border-radius: 4px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: background 0.1s, color 0.1s;
}
.add-toggle-btn:hover { background: var(--bg-tertiary); color: var(--text-primary); }

.add-controls {
  margin-top: 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.add-select {
  width: 100%;
  background: var(--bg-input, var(--bg-tertiary));
  color: var(--text-primary);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 4px 6px;
  font-size: 11px;
}

.add-actions {
  display: flex;
  gap: 4px;
}

.add-btn {
  flex: 1;
  padding: 4px 8px;
  font-size: 11px;
  font-weight: 600;
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}
.add-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.add-btn:hover:not(:disabled) { filter: brightness(1.1); }

.refresh-btn {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-secondary);
  border-radius: 4px;
  padding: 3px 8px;
  font-size: 12px;
  cursor: pointer;
}
.refresh-btn:hover { background: var(--bg-tertiary); color: var(--text-primary); }
.refresh-btn:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
