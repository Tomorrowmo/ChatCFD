<script setup>
import ChatPanel from './components/ChatPanel.vue'
import ArtifactPanel from './components/ArtifactPanel.vue'
</script>

<template>
  <div class="app-layout">
    <div class="chat-side">
      <ChatPanel />
    </div>
    <div class="artifact-side">
      <ArtifactPanel />
    </div>
  </div>
</template>

<style scoped>
.app-layout {
  display: flex;
  width: 100vw;
  height: 100vh;
  overflow: hidden;
}

.chat-side {
  flex: 0 0 55%;
  max-width: 55%;
  height: 100%;
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
}

.artifact-side {
  flex: 0 0 45%;
  max-width: 45%;
  height: 100%;
  display: flex;
  flex-direction: column;
}
</style>
