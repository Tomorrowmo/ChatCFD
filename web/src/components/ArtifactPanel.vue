<script setup>
import { computed } from 'vue'
import { useChatStore } from '../stores/chat.js'
import JsonCard from './JsonCard.vue'
import DataTable from './DataTable.vue'
import MeshBrowser from './MeshBrowser.vue'
import VtpBrowser from './VtpBrowser.vue'

const store = useChatStore()
const { activeArtifacts, activeArtifact, setActiveArtifact, closeArtifactPanel, activeConversation } = store

const sessionId = computed(() => activeConversation.value?.id || 'default')

// Find the wall/surface zone from the loadFile artifact for base model display
const baseZone = computed(() => {
  const wallKeywords = ['wall', 'tri', 'surface', 'body']
  for (const art of activeArtifacts.value) {
    if (art.data?.zones) {
      // Find smallest zone (likely body surface)
      let best = null
      for (const z of art.data.zones) {
        const name = (z.name || '').toLowerCase()
        if (wallKeywords.some(kw => name.includes(kw))) return z.name
        if (!best || (z.point_count || 0) < (best.point_count || Infinity)) best = z
      }
      if (best && art.data.zones.length > 1) return best.name
    }
  }
  return ''
})

// ── File-level tabs (deduplicated by file_path) ──
const fileTabs = computed(() => {
  const seen = new Set()
  return activeArtifacts.value
    .map((art, idx) => ({ ...art, _idx: idx }))
    .filter(art => {
      // loadFile artifacts have zones data
      if (!(art.data && Array.isArray(art.data.zones) && art.data.zones.length > 0)) return false
      const fp = art.data?.file_path || art.title
      if (seen.has(fp)) return false
      seen.add(fp)
      return true
    })
})

// Current active file path (from active artifact's source_file or data.file_path)
const activeFilePath = computed(() => {
  const art = activeArtifact.value
  if (!art) return fileTabs.value[0]?.data?.file_path || null
  // loadFile artifact
  if (art.data?.file_path) return art.data.file_path
  // Result artifact with source_file tag
  if (art.source_file) return art.source_file
  // Fallback
  return fileTabs.value[0]?.data?.file_path || null
})

// ── Result tabs: visual artifacts belonging to the active file (matched by source_file) ──
const resultTabs = computed(() => {
  const fp = activeFilePath.value
  console.log('[ArtifactPanel] activeFilePath:', fp, 'artifacts:', activeArtifacts.value.map(a => ({title: a.title, source_file: a.source_file})))
  return activeArtifacts.value
    .map((art, idx) => ({ ...art, _idx: idx }))
    .filter(art => {
      // Exclude loadFile artifacts (they go in file tabs)
      if (art.data && Array.isArray(art.data.zones) && art.data.zones.length > 0) return false
      // Include visual results: vtp, png
      if ((art.type === 'file' || art.type === 'geometry') && art.file_path) {
        if (!(art.file_path.endsWith('.vtp') || art.file_path.endsWith('.png') || art.file_path.endsWith('.jpg'))) return false
        // Match by source_file (exact match to active file)
        // If source_file is empty/missing, hide it (don't show untagged results everywhere)
        if (fp && (!art.source_file || art.source_file !== fp)) return false
        return true
      }
      return false
    })
})

const activeIdx = computed(() => {
  return store.activeConversation.value?.activeArtifactIndex ?? -1
})

function resultIcon(art) {
  const t = (art.title || '').toLowerCase()
  if (t.includes('stream')) return '\u{1F300}'
  if (t.includes('slice')) return '\u{1FA93}'
  if (t.includes('contour')) return '\u{1F4CA}'
  if (t.includes('clip')) return '\u{2702}'
  if (t.includes('render')) return '\u{1F5BC}'
  if (t.includes('force') || t.includes('moment')) return '#'
  if (t.includes('statistic')) return '#'
  return '\u{1F4D0}'
}

function fileName(art) {
  const fp = art.data?.file_path || art.title || ''
  return fp.split('/').pop()
}

const viewerType = computed(() => {
  const art = activeArtifact.value
  if (!art) return 'none'
  if (art.data && Array.isArray(art.data.zones) && art.data.zones.length > 0) return 'mesh'
  if (art.type === 'numerical') return 'json'
  if ((art.type === 'file' || art.type === 'geometry') && art.file_path) {
    if (art.file_path.endsWith('.csv')) return 'table'
    if (art.file_path.endsWith('.vtp')) return 'vtk'
    if (art.file_path.endsWith('.vtm')) return 'json'
    if (art.file_path.endsWith('.png') || art.file_path.endsWith('.jpg')) return 'image'
  }
  return 'json'
})
</script>

<template>
  <div class="artifact-panel">
    <!-- File tabs row -->
    <div class="file-bar" v-if="fileTabs.length > 0">
      <button
        v-for="ft in fileTabs"
        :key="ft.id"
        class="file-tab"
        :class="{ active: ft._idx === activeIdx || activeFilePath === ft.data?.file_path }"
        @click="setActiveArtifact(ft._idx)"
        :title="ft.data?.file_path"
      >
        <span class="file-name">{{ fileName(ft) }}</span>
      </button>
      <div class="tab-spacer"></div>
      <button class="close-btn" @click="closeArtifactPanel" title="Close">
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5">
          <path d="M6 6 L18 18 M18 6 L6 18" stroke-linecap="round"/>
        </svg>
      </button>
    </div>

    <!-- Result tabs row (under active file) -->
    <div class="result-bar" v-if="resultTabs.length > 0">
      <!-- Mesh tab (always first if file is loaded) -->
      <button
        v-for="ft in fileTabs.filter(f => activeFilePath === f.data?.file_path)"
        :key="'mesh-' + ft.id"
        class="result-tab"
        :class="{ active: ft._idx === activeIdx }"
        @click="setActiveArtifact(ft._idx)"
      >
        <span class="result-label">Mesh</span>
      </button>
      <!-- Computed results -->
      <button
        v-for="rt in resultTabs"
        :key="rt.id"
        class="result-tab"
        :class="{ active: rt._idx === activeIdx }"
        @click="setActiveArtifact(rt._idx)"
        :title="rt.summary"
      >
        <span class="result-label">{{ rt.title }}</span>
      </button>
    </div>

    <!-- Fallback header when no file tabs -->
    <div class="artifact-header" v-if="fileTabs.length === 0">
      <div class="header-left">
        <h2 class="header-title truncate" v-if="activeArtifact">{{ activeArtifact.title }}</h2>
      </div>
      <button class="close-btn" @click="closeArtifactPanel" title="Close">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.5">
          <path d="M6 6 L18 18 M18 6 L6 18" stroke-linecap="round"/>
        </svg>
      </button>
    </div>

    <!-- Viewer area -->
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

      <MeshBrowser
        v-else-if="viewerType === 'mesh'"
        :data="activeArtifact.data"
      />

      <VtpBrowser
        v-else-if="viewerType === 'vtk'"
        :path="activeArtifact.file_path"
        :sessionId="sessionId"
        :baseZone="baseZone"
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

/* ── File tab bar (top) ── */
.file-bar {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 6px 8px 0;
  flex-shrink: 0;
  border-bottom: 1px solid var(--border);
}

.file-tab {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 6px 12px;
  background: transparent;
  border: 1px solid transparent;
  border-bottom: none;
  border-radius: 6px 6px 0 0;
  cursor: pointer;
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
  transition: all 0.15s;
  flex-shrink: 0;
  margin-bottom: -1px;
}
.file-tab:hover {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}
.file-tab.active {
  background: var(--bg-primary);
  color: var(--text-primary);
  border-color: var(--border);
  border-bottom-color: var(--bg-primary);
  font-weight: 500;
}
.file-icon { font-size: 12px; }
.file-name {
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ── Result tab bar (second row) ── */
.result-bar {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 10px;
  flex-shrink: 0;
  border-bottom: 1px solid var(--border);
  overflow-x: auto;
  scrollbar-width: thin;
  background: var(--bg-primary);
}

.result-tab {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  border-radius: 14px;
  cursor: pointer;
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
  transition: all 0.15s;
  flex-shrink: 0;
}
.result-tab:hover {
  background: var(--bg-secondary);
  color: var(--text-primary);
}
.result-tab.active {
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
  font-weight: 500;
}
.result-icon { font-size: 12px; }
.result-label {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.tab-spacer { flex: 1; }

/* ── Fallback header ── */
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

/* ── Close button ── */
.close-btn {
  width: 28px;
  height: 28px;
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

/* ── Viewer ── */
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
