<script setup>
import { computed } from 'vue'
import Sidebar from './components/Sidebar.vue'
import ChatPanel from './components/ChatPanel.vue'
import ArtifactPanel from './components/ArtifactPanel.vue'
import { useChatStore } from './stores/chat.js'

const { state } = useChatStore()
const panelOpen = computed(() => state.artifactPanelOpen)
</script>

<template>
  <div class="app-layout" :class="{ 'panel-open': panelOpen }">
    <!-- Sidebar: absolute, reserves 56px rail -->
    <Sidebar />
    <div class="sidebar-rail"></div>

    <!-- Chat: takes remaining space; chat content centered when panel closed -->
    <div class="chat-side">
      <div class="chat-wrapper">
        <ChatPanel />
      </div>
    </div>

    <!-- Artifact: hidden by default; slides in when open -->
    <div class="artifact-side" v-if="panelOpen">
      <ArtifactPanel />
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
  animation: slide-in 0.25s ease;
}

@keyframes slide-in {
  from { opacity: 0; transform: translateX(20px); }
  to { opacity: 1; transform: translateX(0); }
}
</style>
