<script setup>
import { computed } from 'vue'
import Sidebar from './components/Sidebar.vue'
import ChatPanel from './components/ChatPanel.vue'
import ArtifactPanel from './components/ArtifactPanel.vue'
import ArtifactList from './components/ArtifactList.vue'
import { useChatStore } from './stores/chat.js'

const { state, activeArtifacts, closeArtifactList, openArtifactList } = useChatStore()
const panelOpen = computed(() => state.artifactPanelOpen)
const listVisible = computed(() => state.artifactListVisible)
const hasArtifacts = computed(() => activeArtifacts.value.length > 0)
const artifactCount = computed(() => activeArtifacts.value.length)
</script>

<template>
  <div class="app-layout" :class="{
    'panel-open': panelOpen,
    'list-visible': !panelOpen && listVisible && hasArtifacts
  }">
    <Sidebar />
    <div class="sidebar-rail"></div>

    <div class="chat-side">
      <div class="chat-wrapper">
        <ChatPanel />
      </div>
    </div>

    <!-- State A: full viewer -->
    <div class="artifact-side" v-if="panelOpen">
      <ArtifactPanel />
    </div>

    <!-- State B: narrow history list -->
    <div class="list-side" v-else-if="listVisible && hasArtifacts">
      <div class="list-header">
        <h3>History</h3>
        <span class="count">{{ artifactCount }}</span>
        <button class="close-list-btn" @click="closeArtifactList" title="关闭">&times;</button>
      </div>
      <ArtifactList />
    </div>
  </div>

  <!-- State C: floating reopen button (top-right corner) -->
  <button
    v-if="!panelOpen && !listVisible && hasArtifacts"
    class="reopen-btn"
    @click="openArtifactList"
  >
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M9 5H7a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-2" stroke-linecap="round"/>
      <rect x="9" y="3" width="12" height="8" rx="1"/>
    </svg>
    {{ artifactCount }}
  </button>
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

/* State B: narrow list panel */
.app-layout.list-visible {
  grid-template-columns: 56px 1fr 260px;
}

/* State A: full viewer */
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
  max-width: 800px;
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
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

.list-side {
  grid-column: 3;
  height: 100%;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  border-left: 1px solid var(--border);
  background: var(--bg-secondary);
}

.list-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 16px;
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

.close-list-btn {
  margin-left: auto;
  width: 26px;
  height: 26px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  color: var(--text-secondary);
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 18px;
  line-height: 1;
  transition: background 0.1s, color 0.1s;
}

.close-list-btn:hover {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

/* State C: floating reopen button */
.reopen-btn {
  position: fixed;
  top: 12px;
  right: 12px;
  z-index: 100;
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 6px 12px;
  border: 1px solid var(--border);
  border-radius: 20px;
  background: var(--bg-secondary);
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  transition: background 0.15s, color 0.15s, box-shadow 0.15s;
}

.reopen-btn:hover {
  background: var(--bg-tertiary);
  color: var(--text-primary);
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.25);
}
</style>
