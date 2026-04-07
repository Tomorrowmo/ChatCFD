<script setup>
import { ref, watch, computed } from 'vue'
import VtkViewer from './VtkViewer.vue'
import { useChatStore } from '../stores/chat.js'

const props = defineProps({
  data: Object, // loadFile summary: {zones: [{name, scalars: [{raw_name, display_name, ...}]}]}
})

const { activeConversation } = useChatStore()
const sessionId = computed(() => activeConversation.value?.id || 'default')
const selectedZone = ref('')
const selectedScalar = ref('')

const zones = computed(() => props.data?.zones || [])
const currentZoneScalars = computed(() => {
  const z = zones.value.find((x) => x.name === selectedZone.value)
  return z?.scalars || []
})

// Initialize with first zone + first scalar when data arrives or changes
watch(
  () => props.data,
  (d) => {
    if (d?.zones?.length) {
      if (!selectedZone.value || !d.zones.find((z) => z.name === selectedZone.value)) {
        selectedZone.value = d.zones[0].name
        const firstScalar = d.zones[0].scalars?.[0]
        selectedScalar.value = firstScalar?.raw_name || ''
      }
    }
  },
  { immediate: true }
)

// When zone changes, reset scalar to first available in that zone
watch(selectedZone, () => {
  const scalars = currentZoneScalars.value
  if (scalars.length && !scalars.find((s) => s.raw_name === selectedScalar.value)) {
    selectedScalar.value = scalars[0].raw_name
  }
})
</script>

<template>
  <div class="mesh-browser">
    <div class="controls">
      <label>
        Zone:
        <select v-model="selectedZone">
          <option v-for="z in zones" :key="z.name" :value="z.name">
            {{ z.name }} ({{ z.point_count }} pts)
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
    </div>
    <VtkViewer
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
</style>
