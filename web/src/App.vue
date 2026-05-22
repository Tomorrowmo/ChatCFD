<script setup>
import { computed, ref, watch } from 'vue'
import Sidebar from './components/Sidebar.vue'
import ChatPanel from './components/ChatPanel.vue'
import ArtifactPanel from './components/ArtifactPanel.vue'
import ArtifactList from './components/ArtifactList.vue'
import { useChatStore } from './stores/chat.js'
import { useBreakpoint } from './composables/useBreakpoint.js'

const { state, activeArtifacts, closeArtifactList, openArtifactList } = useChatStore()
const panelOpen = computed(() => state.artifactPanelOpen)
const listVisible = computed(() => state.artifactListVisible)
const hasArtifacts = computed(() => activeArtifacts.value.length > 0)
const artifactCount = computed(() => activeArtifacts.value.length)
const sidebarPinned = ref(false)

const { isMobile } = useBreakpoint()
const mobileDrawerOpen = ref(false)

// Leaving mobile closes the drawer; entering mobile drops the pinned state
// (a pinned rail makes no sense on a phone-width single-column layout).
watch(isMobile, (m) => {
  if (!m) mobileDrawerOpen.value = false
  else sidebarPinned.value = false
})
</script>

<template>
  <div class="app-layout" :class="{
    'panel-open': panelOpen,
    'list-visible': !panelOpen && listVisible && hasArtifacts,
    'sidebar-pinned': sidebarPinned
  }">
    <Sidebar
      :mobile-open="mobileDrawerOpen"
      @update:pinned="v => sidebarPinned = v"
      @navigate="mobileDrawerOpen = false"
    />
    <div class="sidebar-rail"></div>

    <!-- Mobile: tap-to-dismiss scrim behind the drawer -->
    <div
      v-if="isMobile && mobileDrawerOpen"
      class="drawer-overlay"
      @click="mobileDrawerOpen = false"
    ></div>

    <div class="chat-side">
      <div class="chat-wrapper">
        <ChatPanel @open-menu="mobileDrawerOpen = true" />
      </div>
    </div>

    <!-- State A: full viewer (desktop: 3rd column / mobile: full-screen cover) -->
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
  /* Pin the row to the viewport — without this the implicit row is `auto`
     and tall content (e.g. the welcome screen) stretches it past the
     viewport, pushing the chat input out of the clipped area. */
  grid-template-rows: minmax(0, 1fr);
  width: 100%;
  height: 100%;        /* #app is fixed/inset:0, so 100% = real viewport */
  overflow: hidden;
  position: relative;
  transition: grid-template-columns 0.25s ease;
}

/* Sidebar pinned: widen rail to match expanded sidebar */
.app-layout.sidebar-pinned {
  grid-template-columns: 260px 1fr;
}

/* State B: narrow list panel */
.app-layout.list-visible {
  grid-template-columns: 56px 1fr 260px;
}
.app-layout.sidebar-pinned.list-visible {
  grid-template-columns: 260px 1fr 260px;
}

/* State A: full viewer */
.app-layout.panel-open {
  grid-template-columns: 56px 1fr 1fr;
}
.app-layout.sidebar-pinned.panel-open {
  grid-template-columns: 260px 1fr 1fr;
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
  min-width: 0;
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

/* Mobile drawer scrim */
.drawer-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  z-index: 49;
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

/* ───────────── Mobile (≤768px): collapse to single column ───────────── */
@media (max-width: 768px) {
  .app-layout,
  .app-layout.sidebar-pinned,
  .app-layout.list-visible,
  .app-layout.sidebar-pinned.list-visible,
  .app-layout.panel-open,
  .app-layout.sidebar-pinned.panel-open {
    grid-template-columns: 1fr;
  }

  .sidebar-rail {
    display: none;
  }

  .chat-side {
    grid-column: 1;
  }

  /* Artifact / history slide over the chat full-screen instead of a 3rd column */
  .artifact-side,
  .list-side {
    grid-column: 1;
    position: fixed;
    inset: 0;
    z-index: 60;
    border-left: none;
  }
}
</style>
