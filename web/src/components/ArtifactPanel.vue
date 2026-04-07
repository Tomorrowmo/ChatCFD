<script setup>
import { computed, watch } from 'vue'
import { useChatStore } from '../stores/chat.js'
import JsonCard from './JsonCard.vue'
import DataTable from './DataTable.vue'
import SceneViewer from './SceneViewer.vue'

const {
  activeArtifact,
  activeConversation,
  activeSceneLayers,
  closeArtifactPanel,
  addSceneLayer,
} = useChatStore()

const viewerType = computed(() => {
  const art = activeArtifact.value
  if (!art) return 'none'

  // loadFile summary has zones array -> interactive 3D mesh browser
  if (art.data && Array.isArray(art.data.zones) && art.data.zones.length > 0) {
    return 'mesh'
  }

  if (art.type === 'numerical') return 'json'
  if (art.type === 'file' && art.file_path) {
    if (art.file_path.endsWith('.csv')) return 'table'
    if (art.file_path.endsWith('.vtp')) return 'vtk'
    if (art.file_path.endsWith('.vtm')) return 'json'
    if (art.file_path.endsWith('.png') || art.file_path.endsWith('.jpg')) return 'image'
  }
  return 'json'
})

const viewerTypeLabel = computed(() => {
  const t = viewerType.value
  if (t === 'mesh') return '3D Scene'
  if (t === 'vtk') return '3D Scene'
  if (t === 'image') return 'Image'
  if (t === 'table') return 'Data Table'
  if (t === 'json') return 'Result'
  return ''
})

const meshData = computed(() => {
  const art = activeArtifact.value
  if (art && art.data && Array.isArray(art.data.zones)) return art.data
  return null
})

// Use a scene-based viewer for mesh and vtk types
const useSceneViewer = computed(() =>
  viewerType.value === 'mesh' || viewerType.value === 'vtk'
)

// Track which artifacts we have already auto-added as layers to avoid duplicates
const autoAddedArtifacts = new Set()

// When a .vtp artifact is selected, auto-add it as a scene layer
watch(
  activeArtifact,
  (art) => {
    if (!art) return
    const artKey = `${art.id}-${art.file_path || ''}`
    if (autoAddedArtifacts.has(artKey)) return

    if (art.type === 'file' && art.file_path && art.file_path.endsWith('.vtp')) {
      // Check if this file is already a layer
      const layers = activeSceneLayers.value
      const alreadyExists = layers.some(
        l => l.type === 'file' && l.source.filePath === art.file_path
      )
      if (!alreadyExists) {
        // Extract a nice name from the file path
        const parts = art.file_path.replace(/\\/g, '/').split('/')
        const fileName = parts[parts.length - 1].replace('.vtp', '')
        addSceneLayer({
          name: art.title || fileName,
          type: 'file',
          source: { filePath: art.file_path },
        })
      }
      autoAddedArtifacts.add(artKey)
    }

    // Auto-add first zone when mesh artifact is selected and no layers exist
    if (art.data && Array.isArray(art.data.zones) && art.data.zones.length > 0) {
      if (autoAddedArtifacts.has(artKey)) return
      const layers = activeSceneLayers.value
      if (layers.length === 0) {
        const firstZone = art.data.zones[0]
        const firstScalar = firstZone.scalars?.[0]
        const scalarName = firstScalar?.raw_name || ''
        const displayScalar = scalarName || 'geometry'
        addSceneLayer({
          name: `${firstZone.name} (${displayScalar})`,
          type: 'zone',
          source: {
            sessionId: activeConversation.value?.id || 'default',
            zone: firstZone.name,
            scalarName,
          },
        })
      }
      autoAddedArtifacts.add(artKey)
    }
  },
  { immediate: true }
)
</script>

<template>
  <div class="artifact-panel">
    <div class="artifact-header">
      <div class="header-left">
        <span class="header-type">{{ viewerTypeLabel }}</span>
        <h2 class="header-title truncate" v-if="activeArtifact">{{ activeArtifact.title }}</h2>
      </div>
      <button class="close-btn" @click="closeArtifactPanel" title="Close">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.5">
          <path d="M6 6 L18 18 M18 6 L6 18" stroke-linecap="round"/>
        </svg>
      </button>
    </div>

    <div class="viewer-area">
      <div v-if="!activeArtifact" class="viewer-empty">
        <p>No artifact selected</p>
      </div>

      <JsonCard
        v-else-if="viewerType === 'json'"
        :title="activeArtifact.title"
        :summary="activeArtifact.summary"
        :data="activeArtifact.data"
      />

      <DataTable
        v-else-if="viewerType === 'table'"
        :path="activeArtifact.file_path"
      />

      <SceneViewer
        v-else-if="useSceneViewer"
        :meshData="meshData"
      />

      <img
        v-else-if="viewerType === 'image'"
        :src="`http://localhost:8000/api/file/${activeArtifact.file_path.split('/').map(s => encodeURIComponent(s)).join('/')}`"
        class="artifact-image"
        :alt="activeArtifact.title"
      />
    </div>
  </div>
</template>

<style scoped>
.artifact-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-secondary);
  border-left: 1px solid var(--border);
}

.artifact-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px 12px 20px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  min-height: 48px;
}

.header-left {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex: 1;
  min-width: 0;
}

.header-type {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted);
  flex-shrink: 0;
}

.header-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
  margin: 0;
  min-width: 0;
  flex: 1;
}

.truncate {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.close-btn {
  width: 30px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  color: var(--text-secondary);
  border: none;
  border-radius: 6px;
  cursor: pointer;
  flex-shrink: 0;
  transition: background 0.1s, color 0.1s;
}

.close-btn:hover {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

.viewer-area {
  flex: 1;
  overflow: hidden;
  padding: 16px 20px;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.viewer-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-muted);
  gap: 6px;
}

.artifact-image {
  max-width: 100%;
  border-radius: 8px;
  background: var(--bg-tertiary);
}
</style>
