<script setup>
import { computed } from 'vue'
import { useChatStore } from '../stores/chat.js'
import ArtifactList from './ArtifactList.vue'
import JsonCard from './JsonCard.vue'
import DataTable from './DataTable.vue'
import VtkViewer from './VtkViewer.vue'
import MeshBrowser from './MeshBrowser.vue'

const { activeArtifact, state } = useChatStore()

const viewerType = computed(() => {
  const art = activeArtifact.value
  if (!art) return 'none'

  // loadFile summary has zones array → interactive 3D mesh browser
  if (art.data && Array.isArray(art.data.zones) && art.data.zones.length > 0) {
    return 'mesh'
  }

  if (art.type === 'numerical') return 'json'
  if (art.type === 'file' && art.file_path) {
    if (art.file_path.endsWith('.csv')) return 'table'
    if (art.file_path.endsWith('.vtm') || art.file_path.endsWith('.vtp')) return 'vtk'
    if (art.file_path.endsWith('.png') || art.file_path.endsWith('.jpg')) return 'image'
  }
  return 'json'
})
</script>

<template>
  <div class="artifact-panel">
    <div class="artifact-header">
      <h2>Artifacts</h2>
      <span class="count" v-if="state.artifacts.length">{{ state.artifacts.length }}</span>
    </div>

    <div class="viewer-area">
      <div v-if="!activeArtifact" class="viewer-empty">
        <p>No artifact selected</p>
        <p class="viewer-hint">Artifacts from AI responses will appear here</p>
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

      <MeshBrowser
        v-else-if="viewerType === 'mesh'"
        :data="activeArtifact.data"
      />

      <VtkViewer
        v-else-if="viewerType === 'vtk'"
        :path="activeArtifact.file_path"
      />

      <img
        v-else-if="viewerType === 'image'"
        :src="`http://localhost:8000/api/file/${activeArtifact.file_path}`"
        class="artifact-image"
        :alt="activeArtifact.title"
      />
    </div>

    <ArtifactList />
  </div>
</template>

<style scoped>
.artifact-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-secondary);
}

.artifact-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.artifact-header h2 {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.count {
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 10px;
  background: var(--accent);
  color: #fff;
  font-weight: 600;
}

.viewer-area {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
  min-height: 0;
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

.viewer-hint {
  font-size: 12px;
}

.artifact-image {
  max-width: 100%;
  border-radius: 8px;
  background: var(--bg-tertiary);
}
</style>
