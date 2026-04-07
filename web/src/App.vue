<script setup>
import { computed } from 'vue'
import Sidebar from './components/Sidebar.vue'
import ChatPanel from './components/ChatPanel.vue'
import ArtifactPanel from './components/ArtifactPanel.vue'
import ArtifactList from './components/ArtifactList.vue'
import { useChatStore } from './stores/chat.js'

const { state, activeArtifacts } = useChatStore()
const panelOpen = computed(() => state.artifactPanelOpen)
const hasArtifacts = computed(() => activeArtifacts.value.length > 0)
</script>

<template>
  <div class="app-layout" :class="{ 'panel-open': panelOpen || hasArtifacts }">
    <Sidebar />
    <div class="sidebar-rail"></div>

    <div class="chat-side">
      <div class="chat-wrapper">
        <ChatPanel />
      </div>
    </div>

    <!-- Right panel: viewer when open, artifact list when closed (if any artifacts exist) -->
    <div class="artifact-side" v-if="panelOpen || hasArtifacts">
      <ArtifactPanel v-if="panelOpen" />
      <div v-else class="artifact-list-panel">
        <div class="list-header">
          <h3>Artifacts</h3>
          <span class="count">{{ activeArtifacts.length }}</span>
        </div>
        <ArtifactList />
      </div>
    </div>
  </div>
</template>

<style scoped>
.app-layout {
  display: grid;
  grid-template-columns: 56px 1fr;
  width: 100vw;
  height: 100vh;
  overflow: hidden;
  position: relative;
  transition: grid-template-columns 0.25s ease;
}

.app-layout.panel-open {
  grid-template-columns: 56px 1fr 1fr;
}

.sidebar-rail {
  grid-column: 1;
}

.chat-side {
  grid-column: 2;
  height: 100%;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  display: flex;
  justify-content: center;
}

.chat-wrapper {
  width: 100%;
  max-width: 900px;
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.app-layout.panel-open .chat-wrapper {
  max-width: none;
}

.artifact-side {
  grid-column: 3;
  height: 100%;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  border-left: 1px solid var(--border);
  background: var(--bg-secondary);
}

.artifact-list-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.list-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 20px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.list-header h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.count {
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 10px;
  background: var(--accent);
  color: #fff;
  font-weight: 600;
}
</style>
